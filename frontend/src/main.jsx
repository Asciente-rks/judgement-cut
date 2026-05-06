import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import { installSecurityHardening } from "./lib/security";
import "./index.css";

installSecurityHardening();

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
