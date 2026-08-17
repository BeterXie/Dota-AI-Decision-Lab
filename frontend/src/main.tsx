import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ProductRoot } from "./ProductRoot";
import "./styles.scss";
import "./auth.scss";
import "./auth-account.scss";
import "./design/player-first-v2.css";
import "./design/rosh-direction.css";
import "./design/player-layout-v3.css";
import "./design/product-shell.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 2000,
      refetchOnWindowFocus: false
    }
  }
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ProductRoot />
    </QueryClientProvider>
  </React.StrictMode>
);
