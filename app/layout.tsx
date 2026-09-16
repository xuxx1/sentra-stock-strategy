import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "舆策 SENTRA｜舆情驱动短线策略系统",
  description: "融合舆情、行业关联、资金流与研报信息的 5 日短线交易策略决策大屏。",
  icons: { icon: "/favicon.svg", shortcut: "/favicon.svg" },
  openGraph: {
    title: "舆策 · SENTRA",
    description: "舆情驱动的短线策略决策系统",
    images: [{ url: "/og.png", width: 1536, height: 1024 }],
  },
  twitter: { card: "summary_large_image", images: ["/og.png"] },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
