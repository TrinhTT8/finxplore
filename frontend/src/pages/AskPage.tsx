import { DISCLAIMER } from "../lib/config";

// TODO (Phase 4): FR-11 sign-in (Cognito/Amplify), FR-14 question -> table + explanation + SQL,
// FR-15 remaining quota, FR-16 "Was this helpful?".
export default function AskPage() {
  return (
    <section>
      <h1>Ask the AI analyst</h1>
      <p>Ask a question in plain English and get a table, a simple explanation and the SQL used.</p>
      <p className="hint">Coming in Phase 4. {DISCLAIMER}</p>
    </section>
  );
}
