import { NavLink, Outlet } from "react-router-dom";
import { DISCLAIMER } from "../lib/config";

export default function Layout() {
  return (
    <div className="app">
      <header className="site-header">
        <NavLink to="/" className="brand">
          FinXplore
        </NavLink>
        <nav aria-label="Main">
          <NavLink to="/compare">Compare</NavLink>
          <NavLink to="/ask">Ask the AI analyst</NavLink>
        </nav>
      </header>
      <main className="content">
        <Outlet />
      </main>
      <footer className="site-footer">
        <p>{DISCLAIMER}</p>
        <p>Data: SEC EDGAR company filings.</p>
      </footer>
    </div>
  );
}
