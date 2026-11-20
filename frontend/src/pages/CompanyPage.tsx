import { useParams } from "react-router-dom";

// TODO (Phase 3): FR-6 charts per metric (Recharts) with a data table behind each,
// FR-8 sector context, FR-10 "Data as of" date, link to source filing.
// TODO (Phase 4): FR-12 AI snapshot, FR-13 "Explain this".
export default function CompanyPage() {
  const { ticker = "" } = useParams();
  return (
    <section>
      <h1>{ticker.toUpperCase()}</h1>
      <p>Company page coming in Phase 3.</p>
    </section>
  );
}
