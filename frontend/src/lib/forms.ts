/**
 * After a refused submission, go to what has to be corrected: the first field that carries an error, or failing
 * that the first message. The message sits next to its field, which can be far above the button that was pressed.
 */
export function focusFirstInvalid(form: HTMLElement): void {
  // Once React has rendered the errors.
  window.setTimeout(() => {
    const field = form.querySelector<HTMLElement>('[aria-invalid="true"]');
    if (field) {
      field.focus();
      return;
    }
    form.querySelector<HTMLElement>('[role="alert"]')?.scrollIntoView({ block: "center" });
  }, 0);
}
