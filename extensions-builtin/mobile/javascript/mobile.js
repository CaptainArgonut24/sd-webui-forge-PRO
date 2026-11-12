(function () {
    let isSetupForMobile = false;
    const mobileBreakpoint = window.matchMedia("(max-width: 900px)");

    function isMobile() {
        return mobileBreakpoint.matches;
    }

    function reportWindowSize() {
        // not applicable for compact prompt layout
        if (gradioApp().querySelector(".toprow-compact-tools")) return;

        const currentlyMobile = isMobile();
        if (currentlyMobile === isSetupForMobile) return;
        isSetupForMobile = currentlyMobile;

        for (const tab of ["txt2img", "img2img"]) {
            const button = gradioApp().getElementById(tab + "_generate_box");
            const target = gradioApp().getElementById(currentlyMobile ? tab + "_results" : tab + "_actions_column");
            if (!button || !target) continue;

            target.insertBefore(button, target.firstElementChild);

            const results = gradioApp().getElementById(tab + "_results");
            if (results) results.classList.toggle("mobile", currentlyMobile);
        }
    }

    mobileBreakpoint.addEventListener("change", reportWindowSize);

    onUiLoaded(reportWindowSize);
})();
