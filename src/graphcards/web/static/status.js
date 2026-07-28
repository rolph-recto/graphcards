"use strict";

for (const control of document.querySelectorAll("[data-submit-on-change]")) {
  control.addEventListener("change", () => control.form?.requestSubmit());
}
