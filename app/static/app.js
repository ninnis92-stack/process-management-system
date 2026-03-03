(function () {
  const ***REMOVED***leInput = document.getElementById("***REMOVED***leInput");
  const pasteZone = document.getElementById("pasteZone");
  const preview = document.getElementById("preview");
  if (!***REMOVED***leInput || !pasteZone || !preview) return;

  const dt = new DataTransfer();

  function refreshPreview() {
    preview.innerHTML = "";
    for (const ***REMOVED***le of dt.***REMOVED***les) {
      const img = document.createElement("img");
      img.className = "preview-img";
      img.alt = ***REMOVED***le.name;
      img.src = URL.createObjectURL(***REMOVED***le);
      preview.appendChild(img);
    }
    ***REMOVED***leInput.***REMOVED***les = dt.***REMOVED***les;
  }

  function addFile(***REMOVED***le) {
    if (!***REMOVED***le.type.startsWith("image/")) return;
    dt.items.add(***REMOVED***le);
    refreshPreview();
  }

  pasteZone.addEventListener("click", () => pasteZone.focus());
  pasteZone.setAttribute("tabindex", "0");

  pasteZone.addEventListener("paste", (e) => {
    const items = e.clipboardData?.items || [];
    for (const item of items) {
      if (item.type.startsWith("image/")) {
        const ***REMOVED***le = item.getAsFile();
        if (***REMOVED***le) addFile(***REMOVED***le);
      }
    }
  });

  pasteZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    pasteZone.classList.add("paste-zone-hover");
  });
  pasteZone.addEventListener("dragleave", () => {
    pasteZone.classList.remove("paste-zone-hover");
  });
  pasteZone.addEventListener("drop", (e) => {
    e.preventDefault();
    pasteZone.classList.remove("paste-zone-hover");
    const ***REMOVED***les = e.dataTransfer?.***REMOVED***les || [];
    for (const f of ***REMOVED***les) addFile(f);
  });

  ***REMOVED***leInput.addEventListener("change", () => {
    dt.items.clear();
    for (const f of ***REMOVED***leInput.***REMOVED***les) addFile(f);
  });
})();