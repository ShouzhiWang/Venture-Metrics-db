type Props = {
  value?: string;
};

const LABELS: Record<string, string> = {
  public: "Public",
  obtainable: "Public",
  private: "Private",
  not_obtainable: "Not available",
  unclear: "Unclear",
};

function friendlyLabel(raw: string): string {
  const key = raw.toLowerCase().replace(/[\s-]/g, "_");
  return LABELS[key] ?? raw;
}

export function AvailabilityBadge({ value }: Props) {
  if (!value) return null;
  const normalized = value.toLowerCase();
  const tone = normalized.includes("private")
    ? "private"
    : normalized === "not_obtainable" || normalized.includes("not_obtain")
      ? "none"
      : normalized.includes("public") || normalized === "obtainable"
        ? "public"
        : "unclear";
  return (
    <span className={`availability ${tone}`}>
      {friendlyLabel(value)}
    </span>
  );
}
