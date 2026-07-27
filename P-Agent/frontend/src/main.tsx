/** P-Agent 프론트엔드 진입점. */
import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import "./styles.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("root 요소를 찾을 수 없습니다.");
}

ReactDOM.createRoot(container).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
