export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

export const fmt = {
  money(n: number, currency = "USD"): string {
    return new Intl.NumberFormat("en-US", { style: "currency", currency, signDisplay: "exceptZero" }).format(n);
  },
  date(iso: string): string {
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  },
};
