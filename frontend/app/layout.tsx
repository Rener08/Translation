import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "YouTube 翻译助手",
  description:
    "A local YouTube translation and rewrite GUI for transcription, translation, content rewrite, and follow-up chat.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
