import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { App } from "./App";
import "./global.css";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("index.html has no #root element");
}

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
