"""Scientific core of SolarWise DZ.

Pure, deterministic engines with no database, HTTP or clock dependency.  Each
stage of the pipeline lives in its own module and is independently testable:

==================  ==========================================================
``provenance``      MEASURED / MODELLED / SYNTHETIC / UNKNOWN and propagation
``units``           unit parsing and conversion to canonical units
``timeline``        regular analysis grid in the plant's local time
``data_quality``    series-level validation
``baseline``        expected energy (supplied, engineering model, clean
                    reference, PVGIS typical year)
``gap``             performance gap and its significance
``attribution``     factor chain (irradiance, temperature, degradation,
                    downtime, equipment, curtailment, soiling, residual)
``trend``           drift, level shifts, post-rain recovery
``devices``         device-to-fleet comparison
``intraday``        shading and curtailment signatures
``diagnostics``     hypotheses with support levels, conflicts
``recoverable``     recoverable energy from measured soiling
``economics``       cleaning cost / benefit scenarios
``evidence``        decision gates and data-adequacy grade
``decision``        CLEAN_NOW / MONITOR / INVESTIGATE
``explanation``     deterministic plain-language explanation
``pipeline``        wiring of all stages
==================  ==========================================================
"""
