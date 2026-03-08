import { Controller } from "stimulus";

export default class extends Controller {
  connect() {
    // use focusin/focusout to capture events during bubbling phase
    this.element.addEventListener("focusin", this.onFocus.bind(this));
    this.element.addEventListener("focusout", this.onBlur.bind(this));
  }

  onFocus(event) {
    const wrapper = event.target.closest(".mb-3");
    if (wrapper) wrapper.classList.add("field-focused");
  }

  onBlur(event) {
    const wrapper = event.target.closest(".mb-3");
    if (wrapper) wrapper.classList.remove("field-focused");
  }
}
