export type CallBrief = {
  summary: string;
  needs: string[];
  objections: string[];
  unresolvedIssues: string[];
};

/** Only the compact display fields; never copy CRM/memory/debug objects. */
export function readCallBrief(value: unknown): CallBrief | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const source = value as Record<string, unknown>;
  const text = (value: unknown, limit: number) => typeof value === "string" ? value.trim().slice(0, limit) : "";
  const list = (value: unknown) => Array.isArray(value)
    ? [...new Set(value.slice(0, 12).map(item => text(item, 1000)).filter(Boolean))]
    : [];
  const brief: CallBrief = {
    summary: text(source.summary, 4000),
    needs: list(source.needs),
    objections: list(source.objections),
    unresolvedIssues: list(source.unresolved_issues ?? source.unresolvedIssues),
  };
  return brief.summary || brief.needs.length || brief.objections.length || brief.unresolvedIssues.length ? brief : null;
}
