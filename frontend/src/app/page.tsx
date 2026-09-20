import HealthStatus from "@/components/HealthStatus";

export default function Home() {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center p-8">
      <h1 className="text-2xl font-bold mb-6">KnowledgeFlow AI — Foundation</h1>
      <div className="w-full max-w-md">
        <HealthStatus />
      </div>
    </main>
  );
}