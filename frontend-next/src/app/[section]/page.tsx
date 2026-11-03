import { Dashboard, SECTIONS, type Section } from "@/components/dashboard";

export const dynamicParams = false;
export function generateStaticParams() {
  return SECTIONS.filter((section) => section !== "overview").map((section) => ({ section }));
}
export default async function SectionPage({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  const { section } = await params;
  return <Dashboard section={section as Section} />;
}
