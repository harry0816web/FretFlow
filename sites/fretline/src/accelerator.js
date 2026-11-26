const BACKEND_LABELS = { cuda: "NVIDIA CUDA", mps: "Apple MPS", cpu: "CPU" };

/** Describe which accelerator ran a separation job, or null if unknown. */
export function acceleratorLabel(diagnostics) {
  const accelerator = diagnostics?.accelerator;
  if (!accelerator?.backend) return null;
  const backend = BACKEND_LABELS[accelerator.backend] ?? accelerator.backend;
  return accelerator.name ? `${backend} · ${accelerator.name}` : backend;
}

/** Explain a job that is still waiting for a worker to claim it. */
export function queuedHint(job) {
  return job?.status === "QUEUED" ? "Waiting for an inference worker" : null;
}
