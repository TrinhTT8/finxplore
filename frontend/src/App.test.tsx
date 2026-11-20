import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import { GLOSSARY } from "./lib/glossary";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("App", () => {
  it("shows the disclaimer on every page", () => {
    renderAt("/");
    expect(screen.getByText(/not investment advice/i)).toBeInTheDocument();
  });

  it("renders a company page from the URL", () => {
    renderAt("/company/aapl");
    expect(screen.getByRole("heading", { name: "AAPL" })).toBeInTheDocument();
  });

  it("gives every glossary metric a definition and example", () => {
    for (const entry of Object.values(GLOSSARY)) {
      expect(entry.definition.length).toBeGreaterThan(10);
      expect(entry.example.length).toBeGreaterThan(10);
    }
  });
});
