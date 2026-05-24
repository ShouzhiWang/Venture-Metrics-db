type Props = {
  quote?: string;
};

export function EvidenceBlock({ quote }: Props) {
  if (!quote) return null;
  return <blockquote className="evidence">{quote}</blockquote>;
}
