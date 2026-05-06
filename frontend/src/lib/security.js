const PROD = import.meta.env.PROD;

const NOOP = () => undefined;

const CONSOLE_METHODS = [
  "log",
  "info",
  "warn",
  "error",
  "debug",
  "trace",
  "table",
  "group",
  "groupCollapsed",
  "groupEnd",
  "dir",
  "dirxml",
  "count",
  "assert",
  "profile",
  "profileEnd",
  "time",
  "timeEnd",
];

function shouldBlockKey(event) {
  if (event.key === "F12") return true;
  const key = (event.key || "").toUpperCase();
  if ((event.ctrlKey || event.metaKey) && event.shiftKey) {
    if (key === "I" || key === "J" || key === "C") return true;
  }
  if ((event.ctrlKey || event.metaKey) && (key === "U" || key === "S")) {
    return true;
  }
  return false;
}

export function installSecurityHardening() {
  if (!PROD) return;

  document.addEventListener(
    "contextmenu",
    (event) => event.preventDefault(),
    { capture: true },
  );

  document.addEventListener(
    "keydown",
    (event) => {
      if (shouldBlockKey(event)) {
        event.preventDefault();
        event.stopPropagation();
      }
    },
    { capture: true },
  );

  for (const method of CONSOLE_METHODS) {
    try {

      console[method] = NOOP;
    } catch (_err) {

    }
  }

  setInterval(() => {
    try {

      console.clear();
    } catch (_err) {

    }
  }, 1500);
}
