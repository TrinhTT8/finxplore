import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import HomePage from "./pages/HomePage";
import CompanyPage from "./pages/CompanyPage";
import ComparePage from "./pages/ComparePage";
import AskPage from "./pages/AskPage";
import NotFoundPage from "./pages/NotFoundPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
        <Route path="company/:ticker" element={<CompanyPage />} />
        <Route path="compare" element={<ComparePage />} />
        <Route path="ask" element={<AskPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
