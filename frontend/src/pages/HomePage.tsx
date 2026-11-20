import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import MetricTooltip from "../components/MetricTooltip";

export default function HomePage() {
  const [query, setQuery] = useState("");
  const navigate = useNavigate();

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const ticker = query.trim().toUpperCase();
    if (ticker) navigate(`/company/${encodeURIComponent(ticker)}`);
  }

  return (
    <section className="hero">
      <h1>Understand any S&amp;P 500 company, in plain English</h1>
      <p>
        Look up a company to see how it makes money, how healthy it is, and how it compares to its
        sector. No finance background needed.
      </p>
      {/* TODO (FR-5): autocomplete from /companies/search */}
      <form onSubmit={onSubmit} role="search" className="search">
        <label htmlFor="company-search" className="visually-hidden">
          Search by ticker or company name
        </label>
        <input
          id="company-search"
          placeholder="Try AAPL, KO or PEP"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button type="submit">Explore</button>
      </form>
      <p className="hint">
        New to this? Hover any term, like <MetricTooltip metric="free_cash_flow" />, to see what it
        means.
      </p>
    </section>
  );
}
