type Props = {
  value?: string;
};

export function AvailabilityBadge({ value }: Props) {
  const normalized = (value || "unclear").toLowerCase();
  const tone = normalized.includes("private")
    ? "private"
    : normalized.includes("not_obtainable")
      ? "none"
      : normalized.includes("public") || normalized.includes("obtainable")
        ? "public"
        : "unclear";
  return <span className={`availability ${tone}`}>{value || "unclear"}</span>;
}
