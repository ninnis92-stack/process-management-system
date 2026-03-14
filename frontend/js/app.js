
import "./style.css";
import { Application } from "stimulus";
import FieldFocusController from "./controllers/field_focus_controller";
import "./modules/autosave";
import "./modules/theme";

// Only register onboarding controller if onboarding element exists
if (document.querySelector('[data-controller="onboarding"]')) {
	import("./controllers/onboarding_controller").then(({ default: OnboardingController }) => {
		const application = Application.start();
		application.register("onboarding", OnboardingController);
	});
}

// Only load camera module if camera button exists
if (document.querySelector('[data-camera-target]')) {
	import("./modules/camera").then((mod) => {
		if (mod && mod.default) mod.default();
	});
}

// Always register field-focus controller
const application = Application.start();
application.register("field-focus", FieldFocusController);
