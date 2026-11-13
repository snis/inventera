/**
 * Home Assistant Theme Bridge
 * Automatically inherits theme colors, semantic/state colors (green/on, red/off, orange/warning),
 * and dark/light mode when loaded inside Home Assistant Ingress, iframe, or dashboard Webview.
 */
(function() {
    function applyHaTheme() {
        try {
            if (window.parent && window.parent !== window) {
                const parentStyles = window.parent.getComputedStyle(window.parent.document.documentElement);
                const haVars = [
                    '--primary-color',
                    '--dark-primary-color',
                    '--light-primary-color',
                    '--accent-color',
                    '--primary-background-color',
                    '--secondary-background-color',
                    '--card-background-color',
                    '--primary-text-color',
                    '--secondary-text-color',
                    '--disabled-text-color',
                    '--divider-color',
                    '--success-color',
                    '--warning-color',
                    '--error-color',
                    '--info-color',
                    '--green-color',
                    '--orange-color',
                    '--amber-color',
                    '--deep-orange-color',
                    '--red-color',
                    '--state-active-color',
                    '--state-inactive-color',
                    '--state-on-color',
                    '--state-off-color',
                    '--label-badge-green',
                    '--label-badge-yellow',
                    '--label-badge-red'
                ];
                haVars.forEach(v => {
                    const val = parentStyles.getPropertyValue(v);
                    if (val && val.trim()) {
                        document.documentElement.style.setProperty(v, val.trim());
                    }
                });

                const haBg = parentStyles.getPropertyValue('--primary-background-color');
                if (haBg && haBg.trim()) {
                    document.body.style.background = haBg.trim();
                    const bgWrapper = document.querySelector('.background_wrapper');
                    if (bgWrapper) {
                        bgWrapper.style.opacity = '0.05';
                    }
                }
            }
        } catch (e) {
            // Cross-origin restriction (safe fallback)
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', applyHaTheme);
    } else {
        applyHaTheme();
    }

    try {
        if (window.parent && window.parent !== window) {
            const observer = new MutationObserver(applyHaTheme);
            observer.observe(window.parent.document.documentElement, {
                attributes: true,
                attributeFilter: ['style', 'class']
            });
        }
    } catch(e) {}
})();
