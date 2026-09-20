"use client";

import { useEffect, useState } from "react";
import { getHealth, HealthResponse } from "@/lib/api";

type Status = "loading" | "connected" | "error";

export default function HealthStatus() {
  const [status, setStatus] = useState<Status>("loading");
  const [details, setDetails] = useState<HealthResponse | null>(null);

  useEffect(() => {
    getHealth()
      .then((data) => {
        setDetails(data);
        setStatus(data.db_connected ? "connected" : "error");
      })
      .catch(() => {
        setStatus("error");
      });
  }, []);

  const colorClass =
    status === "connected"
      ? "bg-green-100 text-green-800 border-green-300"
      : status === "error"
      ? "bg-red-100 text-red-800 border-red-300"
      : "bg-gray-100 text-gray-700 border-gray-300";

  const label =
    status === "connected"
      ? "Backend Connected"
      : status === "error"
      ? "Backend Unreachable"
      : "Checking backend...";

  return (
    <div className={`rounded-lg border p-4 ${colorClass}`}>
      <p className="font-semibold">{label}</p>
      {details && (
        <pre className="mt-2 text-sm opacity-80">
          {JSON.stringify(details, null, 2)}
        </pre>
      )}
    </div>
  );
}