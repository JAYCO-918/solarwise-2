"""Command line interface.

``solarwise serve``            run the web application
``solarwise migrate``          create or upgrade the database schema
``solarwise create-user``      add an account (the password is read from the terminal or an environment variable)
``solarwise seed-demo``        create the demonstration plant and its synthetic datasets
``solarwise check-config``     show the effective configuration and what is wrong with it
``solarwise openapi``          write the OpenAPI description of the API
``solarwise scenarios``        list the demonstration scenarios and what the engine decides for each
``solarwise scenario KEY``     run one demonstration scenario
``solarwise export-demo``      write the demonstration scenarios as files in the upload format
``solarwise analyze FILE``     analyse a file without a database (advisory result only)
"""

from __future__ import annotations

import argparse
import csv
import getpass
import io
import json
import os
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from solarwise import __version__
from solarwise.core.models import DeviceSpec, EvidenceRecord, PlantSpec
from solarwise.core.pipeline import AnalysisError, AnalysisInput, AnalysisOptions, AnalysisResult, run_analysis
from solarwise.core.provenance import EvaluationContext
from solarwise.demo.generator import DEFAULT_SEED, SYNTHETIC_STATEMENT
from solarwise.demo.run import run_scenario, scenario_table
from solarwise.demo.scenarios import SCENARIO_KEYS, Scenario, build_all, build_scenario
from solarwise.ingestion.parser import ParseError, parse_upload
from solarwise.ingestion.schema import unfilled_placeholders
from solarwise.ingestion.validator import ValidationReport, validate_table
from solarwise.reports import ReportMeta, build_document, render_csv, render_html, render_json, render_pdf

EXIT_OK = 0
EXIT_ERROR = 2
#: The analysis ran but the file was refused, so there is no result.
EXIT_REFUSED = 3


class CliError(Exception):
    """A problem to report on stderr without a traceback."""


# --------------------------------------------------------------------------- helpers


def _read_json(path: str, what: str) -> Any:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise CliError(f"cannot read the {what} file {path}: {exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise CliError(f"the {what} file {path} is not valid JSON: {exc.msg} (line {exc.lineno})") from exc
    unfilled = unfilled_placeholders(payload)
    if unfilled:
        fields = ", ".join(unfilled[:8]) + (" ..." if len(unfilled) > 8 else "")
        raise CliError(f"the {what} file {path} is a template that has not been filled in. Still to complete: {fields}")
    return payload


def _validation_problem(what: str, exc: ValidationError) -> CliError:
    lines = [f"the {what} is not valid:"]
    for error in exc.errors(include_url=False, include_context=False, include_input=False)[:12]:
        where = ".".join(str(part) for part in error["loc"]) or "(root)"
        lines.append(f"  {where}: {error['msg']}")
    return CliError("\n".join(lines))


def _write(out: str | None, content: str | bytes, stream: Any) -> None:
    if out is None or out == "-":
        if isinstance(content, bytes):
            raise CliError("a PDF cannot be written to the terminal: use --out FILE")
        stream.write(content if content.endswith("\n") else content + "\n")
        return
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    print(f"written: {path}", file=sys.stderr)


def summary_text(result: AnalysisResult) -> str:
    """The result in a form that fits a terminal.  Everything in it comes from the engine."""
    rec = result.recommendation
    gap = result.gap

    def pct(value: float | None) -> str:
        return "not available" if value is None else f"{value:.2f} %"

    interval = "daily" if result.interval_minutes == 1440 else f"{result.interval_minutes}-minute"
    lines = [
        rec.headline,
        "",
        f"Decision        {rec.decision.value}  (rule {rec.rule}, reason {rec.reason_code.value})",
        f"Simulated       {'yes - not an operational instruction' if rec.simulated else 'no'}",
        f"Authorisation   {'operational' if rec.operational_authorization else 'none - advisory result'}",
        f"Plant           {result.plant.name}",
        f"Period          {result.period_start.isoformat()} to {result.period_end.isoformat()} "
        f"({result.timezone}), {interval} data",
        f"Gap             period {pct(gap.result.relative_gap_pct)}; assessment window "
        f"{pct(gap.window.result.relative_gap_pct)} ({gap.window.start.isoformat()} to {gap.window.end.isoformat()})",
        f"Baseline        {gap.expected.tag.label}",
        f"Production      {gap.actual.tag.label}",
        f"Diagnostic      {result.diagnostics.status.value}",
        f"Data adequacy   {result.evidence.quality.value}",
        f"Economics       {result.economics.verdict.value} ({result.economics.status.value})",
    ]
    for title, items in (
        ("Why", rec.reasons),
        ("Next steps", rec.next_actions),
        ("What would change this decision", rec.would_change_decision),
    ):
        if items:
            lines += ["", title, *[f"  - {item}" for item in items]]
    lines += ["", "Decision gates (CLEAN_NOW needs all of them)"]
    for gate in rec.gates:
        mark = "pass" if gate.passed else ("n/a " if gate.passed is None else "FAIL")
        lines.append(f"  [{mark}] {gate.label}: {gate.detail}")
    if result.disclaimers:
        lines += ["", "Notices", *[f"  - {item}" for item in result.disclaimers]]
    return "\n".join(lines)


def _render(result: AnalysisResult, fmt: str, dataset_name: str | None) -> str | bytes:
    if fmt == "text":
        return summary_text(result)
    if fmt == "result-json":
        return json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False, allow_nan=False)
    meta = ReportMeta(analysis_id=None, dataset_name=dataset_name, dataset_sha256=None, created_at=datetime.now(UTC))
    if fmt == "json":
        return render_json(result, meta)
    if fmt == "csv":
        return render_csv(result, meta)
    document = build_document(result, meta)
    return render_pdf(document) if fmt == "pdf" else render_html(document)


_FORMATS = ("text", "json", "result-json", "html", "pdf", "csv")


# --------------------------------------------------------------------------- installation commands


def _settings() -> Any:
    """The effective settings.  A setting that cannot be used is explained instead of ending in a traceback."""
    from solarwise.config import get_settings

    try:
        return get_settings()
    except ValidationError as exc:
        raise _validation_problem("configuration", exc) from exc


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    _settings()  # checked here, so that a mistake is explained before the server is started
    uvicorn.run(
        "solarwise.api.app:get_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        proxy_headers=args.proxy_headers,
        forwarded_allow_ips=args.forwarded_allow_ips,
        log_level=args.log_level,
    )
    return EXIT_OK


def _session_factory() -> Any:
    from solarwise.db.base import build_engine, build_session_factory
    from solarwise.db.migrate import init_schema

    settings = _settings()
    engine = build_engine(settings.database_url)
    state = init_schema(engine)
    return settings, build_session_factory(engine), state


def cmd_migrate(args: argparse.Namespace) -> int:
    _, _, state = _session_factory()
    print(f"database schema: {state}")
    return EXIT_OK


def cmd_create_user(args: argparse.Namespace) -> int:
    from solarwise.db.base import session_scope
    from solarwise.db.models import Role
    from solarwise.services import users as user_service
    from solarwise.services.errors import ServiceError

    password = os.environ.get(args.password_env)
    if password is None:
        if not sys.stdin.isatty():
            raise CliError(f"no terminal to ask for the password: set the {args.password_env} environment variable")
        password = getpass.getpass("Password: ")
        if getpass.getpass("Repeat the password: ") != password:
            raise CliError("the two passwords differ")
    _, factory, _ = _session_factory()
    try:
        with session_scope(factory) as db:
            user = user_service.create_user(
                db, email=args.email, password=password, full_name=args.name, role=Role(args.role)
            )
            print(f"account created: {user.email} ({user.role})")
    except ServiceError as exc:
        raise CliError(str(exc)) from exc
    return EXIT_OK


def cmd_seed_demo(args: argparse.Namespace) -> int:
    from solarwise.db.base import session_scope
    from solarwise.services import demo as demo_service
    from solarwise.services import reference as reference_service

    _, factory, _ = _session_factory()
    with session_scope(factory) as db:
        reference_service.sync_reference_values(db)
        created = demo_service.seed_demo(db)
    print(
        f"demonstration content: {created['plants']} plant, {created['datasets']} datasets and "
        f"{created['analyses']} analyses created (existing content is left as it is)"
    )
    print("Every demonstration dataset is synthetic. Start the server with SOLARWISE_DEMO_MODE=true to open it.")
    return EXIT_OK


def cmd_check_config(args: argparse.Namespace) -> int:
    from solarwise.config import Settings

    try:
        settings = Settings()
    except ValidationError as exc:
        raise _validation_problem("configuration", exc) from exc
    database = settings.database_url.split("@")[-1] if "@" in settings.database_url else settings.database_url
    rows = [
        ("environment", settings.environment),
        ("database", database),
        ("demonstration mode", "on" if settings.demo_mode else "off"),
        ("sign-up", "open: visitors can create their own account (role ENGINEER)" if settings.allow_registration
         else "closed: accounts are created by an administrator"),
        ("secret key", "random, valid for this process only" if settings.secret_key_is_ephemeral else "configured"),
        ("allowed hosts", ", ".join(settings.allowed_hosts) or "(none)"),
        ("CORS origins", ", ".join(settings.cors_origins) or "(none: same origin only)"),
        ("frame ancestors", settings.frame_ancestors),
        ("upload limit", f"{settings.max_upload_mb} MB"),
        ("external data", "NASA POWER and PVGIS on request" if settings.external_data_enabled else "disabled"),
        ("language model",
         f"{settings.ai_provider}, model {settings.ai_model}"
         + (f", at {settings.ai_base_url}" if settings.ai_base_url else "")
         + (", key configured" if settings.ai_api_key else ", no key")
         if settings.ai_enabled
         else ("off: a provider is set but no model is named (engine text only)" if settings.ai_provider != "none"
               else "off (engine text only)")),
        ("web interface", str(settings.frontend_dist)),
    ]
    for name, value in rows:
        print(f"{name:<20} {value}")
    warnings = []
    if settings.secret_key_is_ephemeral:
        warnings.append("no SOLARWISE_SECRET_KEY: sessions end whenever the server restarts and cannot be shared "
                        "between several server processes")
    if settings.environment != "production":
        warnings.append("environment is not 'production': HSTS is off and a missing secret key is tolerated")
    if settings.allow_registration and settings.environment == "production":
        warnings.append("sign-up is open: whoever can reach this server can create an account, with an e-mail address "
                        "that is not verified (SOLARWISE_ALLOW_REGISTRATION=false closes it)")
    if "*" in settings.allowed_hosts:
        warnings.append("SOLARWISE_ALLOWED_HOSTS accepts any Host header")
    if settings.frame_ancestors.strip() == "*":
        warnings.append("SOLARWISE_FRAME_ANCESTORS='*' lets any site embed the application in a frame")
    if not Path(settings.frontend_dist).joinpath("index.html").is_file():
        warnings.append("the web interface is not built: only the API will be served")
    if settings.is_sqlite:
        warnings.append("SQLite is meant for a single server process; use PostgreSQL for a shared installation")
    for warning in warnings:
        print(f"warning: {warning}")
    return EXIT_OK


def cmd_openapi(args: argparse.Namespace) -> int:
    """The API description, from which the web interface's types are generated."""
    from solarwise.api.app import create_app
    from solarwise.config import Settings

    # Nothing is started: the document depends on the code only, not on the configuration.
    app = create_app(Settings(environment="test", database_url="sqlite://", secret_key="x" * 48))
    _write(args.out, json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", sys.stdout)
    return EXIT_OK


# --------------------------------------------------------------------------- demonstration scenarios


def _context(args: argparse.Namespace) -> EvaluationContext:
    return EvaluationContext.OPERATIONAL if args.operational else EvaluationContext.DEMONSTRATION


def cmd_scenarios(args: argparse.Namespace) -> int:
    context = _context(args)
    rows = []
    for scenario in build_all(args.seed):
        rec = run_scenario(scenario, context).recommendation
        rows.append(
            {
                "key": scenario.key, "title": scenario.title, "decision": rec.decision.value, "rule": rec.rule,
                "simulated": rec.simulated, "operational_authorization": rec.operational_authorization,
                "expected_decision": scenario.expected_decision, "expected_rule": scenario.expected_rule,
            }
        )
    if args.json:
        print(json.dumps({"seed": args.seed, "context": context.value, "scenarios": rows}, indent=2))
        return EXIT_OK
    print(f"Demonstration scenarios (seed {args.seed}, evaluated as {context.value}). All data are synthetic.")
    print(f"{'scenario':<30} {'decision':<12} {'rule':<5} {'simulated':<10} title")
    for row in rows:
        print(f"{row['key']:<30} {row['decision']:<12} {row['rule']:<5} {'yes' if row['simulated'] else 'no':<10} {row['title']}")
    if context is EvaluationContext.OPERATIONAL:
        print("Evaluated as operational data, synthetic values are not evidence: no decision can rest on them.")
    return EXIT_OK


def _scenario(key: str, seed: int) -> Scenario:
    matches = [k for k in SCENARIO_KEYS if k == key or k.split("_", 1)[0].lower() == key.lower()]
    if len(matches) != 1:
        raise CliError(f"unknown scenario {key!r}; choose one of: {', '.join(SCENARIO_KEYS)}")
    return build_scenario(matches[0], seed)


def cmd_scenario(args: argparse.Namespace) -> int:
    scenario = _scenario(args.key, args.seed)
    result = run_scenario(scenario, _context(args))
    if args.format == "text":
        print(f"{scenario.key}: {scenario.title}")
        print(scenario.story)
        print("Injected by the generator: " + "; ".join(scenario.injected))
        print()
    _write(args.out, _render(result, args.format, scenario.metadata.name), sys.stdout)
    return EXIT_OK


def table_csv(columns: Sequence[str], rows: Sequence[dict[str, Any]]) -> str:
    """Rows in the upload format.  Missing values are empty cells; floats keep their full precision."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if row.get(c) is None else (repr(row[c]) if isinstance(row[c], float) else row[c]) for c in columns])
    return out.getvalue()


_EXPORT_README = """\
# Demonstration scenarios

**Every file in this directory is synthetic.** {statement}

The files were written by `solarwise export-demo` (generator seed {seed}, engine {version}) and are
reproduced exactly by running the command again. Do not edit them by hand.

For each scenario:

| File | Content |
|---|---|
| `<scenario>.csv` | time series in the upload format (plant rows first, then one row per device and interval) |
| `<scenario>.metadata.json` | what the file declares: units, provenance of each channel, baseline, synthetic statement |
| `<scenario>.evidence.json` | discrete evidence records attached to the scenario (soiling measurements, logs, inspections) |
| `<scenario>.options.json` | the cleaning and economic assumptions used in the demonstration (illustrative, not prices) |

`plant.json` and `devices.json` describe the demonstration plant. Its name, location and nominal capacity are
public reference information; every technical parameter is an illustrative assumption.

Run one from the files:

    solarwise analyze S02_confirmed_soiling.csv --plant plant.json --devices devices.json \\
        --metadata S02_confirmed_soiling.metadata.json --evidence S02_confirmed_soiling.evidence.json \\
        --options S02_confirmed_soiling.options.json --demonstration

Without `--demonstration` the same command evaluates the file as operational data; synthetic values are then
not accepted as evidence and the engine answers INVESTIGATE.

| Scenario | Shows | Simulated decision |
|---|---|---|
{table}
"""


def cmd_export_demo(args: argparse.Namespace) -> int:
    target = Path(args.out)
    target.mkdir(parents=True, exist_ok=True)
    scenarios = build_all(args.seed)
    first = scenarios[0]
    (target / "plant.json").write_text(json.dumps(first.plant.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    devices = sorted({(d.code, d.capacity_kwp, d.kind) for s in scenarios for d in s.devices})
    (target / "devices.json").write_text(
        json.dumps([{"code": c, "capacity_kwp": k, "kind": kind} for c, k, kind in devices], indent=2) + "\n", encoding="utf-8"
    )
    lines = []
    for scenario in scenarios:
        table = scenario_table(scenario)
        (target / f"{scenario.key}.csv").write_text(table_csv(table.columns, table.rows), encoding="utf-8")
        (target / f"{scenario.key}.metadata.json").write_text(
            json.dumps(scenario.metadata.model_dump(mode="json", exclude_none=True), indent=2) + "\n", encoding="utf-8"
        )
        (target / f"{scenario.key}.evidence.json").write_text(
            json.dumps([r.model_dump(mode="json", exclude_none=True) for r in scenario.evidence], indent=2) + "\n",
            encoding="utf-8",
        )
        options = AnalysisOptions(cleaning=scenario.cleaning, economics=scenario.economics)
        (target / f"{scenario.key}.options.json").write_text(
            json.dumps(options.model_dump(mode="json", exclude_defaults=True), indent=2) + "\n", encoding="utf-8"
        )
        lines.append(f"| `{scenario.key}` | {scenario.title} | {scenario.expected_decision} (rule {scenario.expected_rule}) |")
    (target / "README.md").write_text(
        _EXPORT_README.format(statement=SYNTHETIC_STATEMENT, seed=args.seed, version=__version__, table="\n".join(lines)),
        encoding="utf-8",
    )
    print(f"{len(scenarios)} synthetic scenarios written to {target}")
    return EXIT_OK


# --------------------------------------------------------------------------- offline analysis


def load_case(args: argparse.Namespace) -> tuple[ValidationReport, AnalysisInput | None]:
    """Read and validate the files named on the command line, exactly as an upload would be."""
    from solarwise.services.datasets import import_issues_from, parse_metadata
    from solarwise.services.errors import ServiceError

    try:
        plant = PlantSpec.model_validate(_read_json(args.plant, "plant"))
    except ValidationError as exc:
        raise _validation_problem("plant description", exc) from exc

    devices: dict[str, DeviceSpec] = {}
    if args.devices:
        raw_devices = _read_json(args.devices, "devices")
        if not isinstance(raw_devices, list):
            raise CliError("the devices file must be a JSON list of {code, capacity_kwp, kind}")
        for item in raw_devices:
            try:
                device = DeviceSpec(code=str(item["code"]), capacity_kwp=float(item["capacity_kwp"]),
                                    kind=str(item.get("kind", "INVERTER")))
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise CliError(f"invalid device entry {item!r}: 'code' and a numeric 'capacity_kwp' are required") from exc
            if device.capacity_kwp <= 0:
                raise CliError(f"device {device.code}: capacity_kwp must be positive")
            devices[device.code] = device

    records: list[EvidenceRecord] = []
    if args.evidence:
        raw_records = _read_json(args.evidence, "evidence")
        if not isinstance(raw_records, list):
            raise CliError("the evidence file must be a JSON list of evidence records")
        try:
            records = [EvidenceRecord.model_validate(item) for item in raw_records]
        except ValidationError as exc:
            raise _validation_problem("evidence file", exc) from exc

    options = AnalysisOptions()
    if args.options:
        try:
            options = AnalysisOptions.model_validate(_read_json(args.options, "options"))
        except ValidationError as exc:
            raise _validation_problem("options file", exc) from exc

    path = Path(args.file)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise CliError(f"cannot read {path}: {exc.strerror or exc}") from exc
    try:
        table = parse_upload(data, path.name)
    except ParseError as exc:
        raise CliError(f"{path.name}: {exc}") from exc
    metadata_json = None
    if args.metadata:
        try:
            metadata_json = Path(args.metadata).read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise CliError(f"cannot read the metadata file {args.metadata}: {exc.strerror or exc}") from exc
    try:
        metadata = parse_metadata(metadata_json, table, path.name)
    except ServiceError as exc:
        details = exc.details
        extra = ""
        if isinstance(details, list):
            extra = "".join(
                f"\n  {'.'.join(str(p) for p in d.get('loc', ()))}: {d.get('msg')}" for d in details if isinstance(d, dict)
            )
        elif isinstance(details, dict) and isinstance(details.get("fields"), list):
            extra = "\n  " + ", ".join(str(f) for f in details["fields"][:8])
        raise CliError(f"{exc}{extra}") from exc

    report, parsed = validate_table(table, metadata, plant=plant, known_devices=devices)
    if parsed is None or not report.accepted:
        return report, None
    context = EvaluationContext.DEMONSTRATION if args.demonstration else EvaluationContext.OPERATIONAL
    return report, AnalysisInput(
        plant=plant,
        observations=parsed.observations,
        interval_minutes=parsed.interval_minutes,
        channels=parsed.channels,
        context=context,
        options=options,
        declared_baseline=parsed.baseline,
        device_observations=parsed.device_observations,
        devices=devices,
        device_tag=parsed.device_tag,
        # Evidence given with the case, and the events the file itself carries in its declared event columns.
        records=[*records, *parsed.events],
        import_issues=import_issues_from(report.model_dump(mode="json")),
        dataset_name=metadata.name,
        dataset_disclaimer=metadata.disclaimer,
        # Nothing about this run is recorded: no account, no audit trail, no stored result.  Field work is
        # authorised only by an analysis kept by the platform.
        allow_operational_authorization=False,
    )


def _print_report(report: ValidationReport, stream: Any) -> None:
    print(report.summary, file=stream)
    for issue in report.issues:
        where = f" [{issue.column}]" if issue.column else ""
        count = f" x{issue.count}" if issue.count > 1 else ""
        print(f"  {issue.severity.value:<8} {issue.code}{where}{count}: {issue.message}", file=stream)


def cmd_analyze(args: argparse.Namespace) -> int:
    report, inp = load_case(args)
    if inp is None:
        _print_report(report, sys.stderr)
        return EXIT_REFUSED
    if args.format == "text" or args.verbose:
        _print_report(report, sys.stderr)
    try:
        result = run_analysis(inp)
    except AnalysisError as exc:
        print(f"analysis not possible: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    _write(args.out, _render(result, args.format, inp.dataset_name), sys.stdout)
    return EXIT_OK


def cmd_validate(args: argparse.Namespace) -> int:
    report, inp = load_case(args)
    if args.json:
        print(json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False))
    else:
        _print_report(report, sys.stdout)
    return EXIT_OK if inp is not None else EXIT_REFUSED


# --------------------------------------------------------------------------- parser


def _add_case_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("file", help="CSV or JSON time series in the upload format")
    parser.add_argument("--plant", required=True, help="JSON description of the plant (see data/samples/plant.json)")
    parser.add_argument("--metadata", help="JSON declaring units, provenance and baseline of the file's columns")
    parser.add_argument("--devices", help="JSON list of devices: [{code, capacity_kwp, kind}]")
    parser.add_argument("--evidence", help="JSON list of evidence records (soiling measurements, logs, inspections)")
    parser.add_argument("--options", help="JSON with analysis options: cleaning and economic assumptions, thresholds")
    parser.add_argument(
        "--demonstration", action="store_true",
        help="evaluate as a demonstration: synthetic data are accepted and every decision is marked simulated",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="solarwise",
        description="SolarWise DZ - photovoltaic performance intelligence and cleaning optimisation.",
    )
    parser.add_argument("--version", action="version", version=f"solarwise {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    def add(name: str, handler: Callable[[argparse.Namespace], int], help_text: str) -> argparse.ArgumentParser:
        command = sub.add_parser(name, help=help_text, description=help_text)
        command.set_defaults(handler=handler)
        return command

    serve = add("serve", cmd_serve, "Run the web application (API and, when built, the web interface).")
    serve.add_argument("--host", default="127.0.0.1", help="address to listen on (default: 127.0.0.1)")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true", help="restart on code changes (development only)")
    serve.add_argument("--proxy-headers", action="store_true", help="trust X-Forwarded-* headers from --forwarded-allow-ips")
    serve.add_argument("--forwarded-allow-ips", default="127.0.0.1", help="proxies whose forwarding headers are trusted")
    serve.add_argument("--log-level", default="info", choices=["critical", "error", "warning", "info", "debug"])

    add("migrate", cmd_migrate, "Create the database schema or upgrade it to the current version.")

    user = add("create-user", cmd_create_user, "Create an account. The password is asked on the terminal.")
    user.add_argument("email")
    user.add_argument("--name", default="", help="full name")
    user.add_argument("--role", default="ENGINEER", choices=["ADMIN", "ENGINEER", "VIEWER"])
    user.add_argument("--password-env", default="SOLARWISE_NEW_PASSWORD", metavar="VARIABLE",
                      help="environment variable to read the password from instead of asking (default: %(default)s)")

    add("seed-demo", cmd_seed_demo, "Create the demonstration plant with its synthetic datasets.")
    add("check-config", cmd_check_config, "Show the effective configuration and warn about weak settings.")

    openapi = add("openapi", cmd_openapi, "Write the OpenAPI description of the API.")
    openapi.add_argument("--out", "-o", help="file to write (default: the terminal)")

    scenarios = add("scenarios", cmd_scenarios, "List the demonstration scenarios and the engine's decision for each.")
    scenarios.add_argument("--seed", type=int, default=DEFAULT_SEED)
    scenarios.add_argument("--operational", action="store_true", help="evaluate as operational data instead")
    scenarios.add_argument("--json", action="store_true")

    scenario = add("scenario", cmd_scenario, "Run one demonstration scenario.")
    scenario.add_argument("key", help="scenario key, or its number such as S02")
    scenario.add_argument("--seed", type=int, default=DEFAULT_SEED)
    scenario.add_argument("--operational", action="store_true", help="evaluate as operational data instead")
    scenario.add_argument("--format", choices=_FORMATS, default="text")
    scenario.add_argument("--out", "-o", help="file to write (default: the terminal)")

    export = add("export-demo", cmd_export_demo, "Write the demonstration scenarios as files in the upload format.")
    export.add_argument("--out", "-o", required=True, help="directory to write to")
    export.add_argument("--seed", type=int, default=DEFAULT_SEED)

    analyze = add("analyze", cmd_analyze,
                  "Analyse a file without a database. The result is advisory: it never authorises field work.")
    _add_case_arguments(analyze)
    analyze.add_argument("--format", choices=_FORMATS, default="text")
    analyze.add_argument("--out", "-o", help="file to write (default: the terminal)")
    analyze.add_argument("--verbose", "-v", action="store_true", help="print the validation report as well")

    validate = add("validate", cmd_validate, "Validate a file against its declarations without analysing it.")
    _add_case_arguments(validate)
    validate.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except BrokenPipeError:  # output piped into a pager or `head` that closed early
        return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
