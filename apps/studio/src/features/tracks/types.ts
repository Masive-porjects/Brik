export type TrackStatus =
  | "uploaded"
  | "analyzing"
  | "ready"
  | "mastering"
  | "completed"
  | "error";

export interface Track {
  id: string;
  user_id: string;
  title: string;
  original_filename: string;
  storage_path: string;
  file_size_bytes: number;
  duration_seconds: number | null;
  sample_rate: number | null;
  channels: number | null;
  format: string | null;
  status: TrackStatus;
  draft_parameters?: Record<string, any> | null;
  active_preset?: string | null;
  draft_name?: string | null;
  created_at: string;
  updated_at: string;
  masters?: MasterRecord[];
  drafts?: TrackDraft[];
}

export interface TrackDraft {
  id: string;
  track_id: string;
  user_id: string;
  name: string;
  version_number: number;
  parameters: Record<string, any>;
  active_preset: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CreateTrackInput {
  id?: string;
  title: string;
  original_filename: string;
  storage_path: string;
  file_size_bytes: number;
  duration_seconds?: number | null;
  sample_rate?: number | null;
  channels?: number | null;
  format?: string | null;
  status?: TrackStatus;
  draft_parameters?: Record<string, any> | null;
  active_preset?: string | null;
  draft_name?: string | null;
}

export interface AudioMetadata {
  duration: number;
  sampleRate: number;
  channels: number;
  format: string;
  fileSizeBytes: number;
}

export interface MasterRecord {
  id: string;
  track_id: string;
  user_id: string;
  name?: string | null;
  storage_path: string;
  format: string;
  file_size_bytes: number;
  integrated_lufs: number | null;
  true_peak_db: number | null;
  parameters_applied: Record<string, any>;
  preset_name: string | null;
  created_at: string;
}

export interface CreateMasterInput {
  id?: string;
  track_id: string;
  name?: string | null;
  storage_path: string;
  format: string;
  file_size_bytes: number;
  integrated_lufs?: number | null;
  true_peak_db?: number | null;
  parameters_applied?: Record<string, any>;
  preset_name?: string | null;
}

export type TrackFilterStatus = "all" | "draft" | "completed";

export type TrackEventType =
  | "uploaded"
  | "analyzed"
  | "draft_saved"
  | "reprocessed"
  | "preset_applied"
  | "master_consolidated"
  | "master_downloaded";

export interface TrackEvent {
  id: string;
  track_id: string;
  user_id: string;
  event_type: TrackEventType;
  details: Record<string, any>;
  created_at: string;
}

