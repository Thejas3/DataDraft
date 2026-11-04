import type { Metadata, Viewport } from "next";
import { Atkinson_Hyperlegible_Mono, Atkinson_Hyperlegible_Next, Big_Shoulders, Big_Shoulders_Stencil } from "next/font/google";
import "./globals.css";

// DESIGN.md typography. Google merged "Big Shoulders Display" / "Big Shoulders Stencil
// Display" into the variable "Big Shoulders" / "Big Shoulders Stencil" families; the
// display cut is the high end of the opsz axis.
const display = Big_Shoulders({ subsets: ["latin"], axes: ["opsz"], variable: "--font-display", display: "swap" });
const stamp = Big_Shoulders_Stencil({ subsets: ["latin"], axes: ["opsz"], variable: "--font-stamp", display: "swap" });
const body = Atkinson_Hyperlegible_Next({ subsets: ["latin"], variable: "--font-body", display: "swap" });
const mono = Atkinson_Hyperlegible_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: { default: "DataDraft", template: "%s · DataDraft" },
  description: "Trade rulings, waivers and start/sit for your Sleeper league.",
  robots: { index: false, follow: false },
  other: { "darkreader-lock": "" },
};

export const viewport: Viewport = { colorScheme: "light dark" };

// Runs before paint: the saved theme, else the system preference on first visit, and
// the .js class that opts in to motion (content is visible without it).
const BOOT = `(function(){try{var t=localStorage.getItem("dd-theme");if(!t)t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";document.documentElement.dataset.theme=t;}catch(e){}document.documentElement.classList.add("js");})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${stamp.variable} ${body.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: BOOT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
