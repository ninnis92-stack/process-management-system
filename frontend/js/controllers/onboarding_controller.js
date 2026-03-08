import { Controller } from "stimulus";

export default class extends Controller {
  static targets = ["dismiss"];

  connect() {
    const helpKey = "requestNewHelpDismissed";
    if (!localStorage.getItem(helpKey)) {
      this.show();
    }
  }

  show() {
    try {
      new bootstrap.Offcanvas(this.element).show();
    } catch (e) {
      // ignore if Bootstrap isn't loaded yet
    }
  }

  dismiss() {
    localStorage.setItem("requestNewHelpDismissed", "1");
  }
}
