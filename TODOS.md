# TODOs

## Design

### External WCAG 2.2 AA Review Before Public Launch

- **What:** Have an external accessibility reviewer audit the public Ragstudio site and static proof viewer against WCAG 2.2 Level AA before public launch.
- **Why:** Automated checks and internal keyboard/screen-reader smoke tests can miss real assistive-technology issues, especially in the proof viewer's claim rail, evidence panels, raw artifact links, and long JSON/table previews.
- **Pros:** Improves confidence that the proof viewer is usable by keyboard and screen-reader users; gives the public launch a stronger accessibility posture; catches subtle issues before users report them.
- **Cons:** Adds scheduling or reviewer availability risk before the public launch; may produce remediation work after implementation.
- **Context:** The launch plan now targets WCAG 2.2 Level AA for `/`, `/proof`, `/benchmark`, `/docs`, `/roadmap`, and deep-linked proof details. Internal gates still include axe/Playwright, keyboard-only flow, mobile overflow checks, and manual screen-reader label inspection.
- **Depends on / blocked by:** Requires the `ragstudio-site` implementation and proof viewer to exist in a reviewable preview environment.
