/** Calculator — Alt+C to toggle, or click the small 🧮 button bottom-right. Popup, no
 * backdrop (doesn't block the rest of the app). Near-zero cost until first use: the full
 * panel DOM/CSS is only built on first open. The only always-on costs are one keydown
 * listener and one small launcher button (negligible). */
const Calculator = (() => {
  let built = false;
  let launcherBuilt = false;
  let expr = ""; // raw expression string, e.g. "12+4*3"
  let justEvaluated = false;

