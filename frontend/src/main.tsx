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
import "./design/events-v2.css";
import "./design/match-v2.css";
import "./design/team-v2.css";
import "./design/premium-shell.css";
import "./design/account-v2.css";
import "./design/admin-runtime.css";
import "./design/admin-runtime-advanced.css";
import "./design/final-experience-audit.css";
import "./design/real-data-ux.css";
import "./design/visual-assets-v2.css";
import "./design/typography-refresh.css";

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
