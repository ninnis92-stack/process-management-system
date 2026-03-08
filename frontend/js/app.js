import "./style.css";
import { Application } from "stimulus";
import OnboardingController from "./controllers/onboarding_controller";
import FieldFocusController from "./controllers/field_focus_controller";

const application = Application.start();
application.register("onboarding", OnboardingController);
application.register("field-focus", FieldFocusController);

// additional controllers can be registered here in future
