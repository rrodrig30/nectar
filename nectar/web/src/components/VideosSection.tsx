// Demonstration videos are a planned capability: a curated library of preparation-technique clips
// (drain-and-rinse for potassium, no-added-salt cooking, portioning) the clinician can share with a
// patient. The content and storage pipeline is not built yet, so this section is an honest roadmap
// placeholder rather than a fake player, per the feature backlog.
export function VideosSection(): JSX.Element {
  return (
    <div className="card">
      <h2>Demonstration videos</h2>
      <p className="card-hint">
        A curated library of short preparation-technique videos to share with a patient, tied to the
        techniques the engine recommends.
      </p>
      <div className="videos-roadmap">
        <div className="roadmap-badge">Planned</div>
        <p>
          This library is not yet built. When it lands, each recommended preparation change (for
          example, boil-and-drain to lower potassium, or no-added-salt braising) will link to a short
          clip demonstrating the technique, so the guidance is not only calculated but shown.
        </p>
        <ul className="roadmap-list">
          <li>Clips keyed to intervention classes and preparation methods already in the graph.</li>
          <li>Institution-hosted storage (keeps content on institutional infrastructure).</li>
          <li>Surfaced inline on a remediation, next to the calculated effect.</li>
        </ul>
        <p className="muted">
          Building this requires a content and storage plan; it is tracked as a future item, not a
          shipped feature.
        </p>
      </div>
    </div>
  );
}
