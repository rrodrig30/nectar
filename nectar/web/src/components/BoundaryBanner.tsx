// The intended-use boundary is persistent and non-dismissible (SDD Section 9): NECTAR is
// educational/research software, not medical nutrition therapy. There is deliberately no close
// control. When the engine returns its own boundary string it is shown too, but this banner is
// always present regardless of app state.
export const BOUNDARY_TEXT =
  'Educational and research use only. Not medical nutrition therapy and not validated for ' +
  'individual patient care. Every derived constraint requires physician confirmation; every ' +
  'nutrient value is calculated, not laboratory-measured.';

export function BoundaryBanner(): JSX.Element {
  return (
    <div className="boundary-banner" role="alert" aria-live="polite">
      <strong>Intended use:</strong> {BOUNDARY_TEXT}
    </div>
  );
}
