"use client";

import { useState } from "react";
import {
  Settings as SettingsIcon,
  Database,
  Server,
  Box,
  GitBranch,
  Cpu,
  FileText,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { ProtectedShell } from "@/components/protected-shell";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function SettingsPage() {
  const { user } = useAuth();

  const rows = [
    {
      icon: Database,
      label: "PostgreSQL 15",
      value: "Relational store — users, videos, clips, detections, claims, reports",
    },
    {
      icon: Server,
      label: "FastAPI Backend",
      value: "API + background video processing pipeline",
    },
    {
      icon: Box,
      label: "MinIO (S3)",
      value: "Immutable object storage for originals, clips, frames, policies, reports",
    },
    {
      icon: GitBranch,
      label: "Qdrant",
      value: "Vector store for video evidence + policy chunk semantic retrieval",
    },
    {
      icon: Cpu,
      label: "YOLOv8 / PySceneDetect",
      value: "Object detection + tracking and scene segmentation",
    },
    {
      icon: FileText,
      label: "LLM / VLM / RAG",
      value: "OpenAI-compatible provider with deterministic simulation fallback",
    },
  ];

  const roles = ["INVESTIGATOR", "SECURITY_OFFICER", "REVIEWER", "ADMIN"];

  return (
    <ProtectedShell>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-navy">Settings</h1>
        <p className="text-sm text-slate-500">
          System information, service components, and current user context.
        </p>
      </div>

      <div className="mb-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <SettingsIcon className="h-5 w-5 text-accent" /> Current User
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 text-sm sm:grid-cols-2">
            {user && (
              <>
                <div>
                  <p className="text-slate-500">Name</p>
                  <p className="font-medium text-navy">{user.name}</p>
                </div>
                <div>
                  <p className="text-slate-500">Email</p>
                  <p className="font-medium text-navy">{user.email}</p>
                </div>
                <div>
                  <p className="text-slate-500">Role</p>
                  <div className="mt-1">
                    <Badge variant="default">{user.role}</Badge>
                  </div>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="mb-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Roles</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {roles.map((r) => (
              <Badge key={r} variant="muted">
                {r}
              </Badge>
            ))}
            <p className="w-full text-xs text-slate-500">
              ADMIN and REVIEWER can approve/reject/finalize reports and review claims. All roles
              can upload videos and run investigations.
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Server className="h-5 w-5 text-accent" /> Service Components
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="divide-y divide-slate-100">
            {rows.map((r) => (
              <li key={r.label} className="flex items-start gap-4 py-3">
                <div className="rounded-md bg-navy/10 p-2 text-navy">
                  <r.icon className="h-5 w-5" />
                </div>
                <div>
                  <p className="font-medium text-navy">{r.label}</p>
                  <p className="text-sm text-slate-500">{r.value}</p>
                </div>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </ProtectedShell>
  );
}
