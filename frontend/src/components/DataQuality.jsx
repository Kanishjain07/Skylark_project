// Renders a compact, human-readable data-quality caveat under an answer.
export default function DataQuality({ dataQuality }) {
  if (!dataQuality || Object.keys(dataQuality).length === 0) return null;

  const notes = [];
  for (const board of Object.values(dataQuality)) {
    if (!board) continue;
    const name = board.board_name || "board";
    const completeness = board.overall_completeness_pct;
    const missing = board.missing_by_field || {};
    const worst = Object.entries(missing).slice(0, 2);

    const parts = [];
    if (typeof completeness === "number") {
      parts.push(`${completeness}% complete`);
    }
    if (worst.length) {
      parts.push(
        "gaps in " +
          worst.map(([f, n]) => `${f} (${n})`).join(", ")
      );
    }
    if (parts.length) {
      notes.push(`${name}: ${parts.join(" · ")}`);
    }
  }

  if (!notes.length) return null;

  return (
    <p className="dq">
      <strong>Data quality</strong> — {notes.join("  |  ")}
    </p>
  );
}
