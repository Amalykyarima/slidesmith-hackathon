import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { Supports } from './models';

export interface Source {
  id: string;
  source: string;
  title: string;
  text: string;
}

export interface Pupil {
  id: string;
  code: string;
  year_group: string;
  phase: 'primary' | 'secondary' | 'university';
  status: string;
  need_area: string;
  need_area_label: string;
  needs: string[];
  summary: string;
  strengths: string;
  provision: string[];
  next_review: string | null;
}

export interface ApdrRecord {
  assess: string;
  plan: { outcomes: string[]; provision: string[]; who: string; frequency: string; review_in_weeks: number };
  do: string;
  review: { success_criteria: string[] };
  pupil_voice: string;
  parent_contact: string;
  missing: string[];
}

export interface RecordRow {
  id: string;
  note: string;
  record: ApdrRecord;
  sources: Source[];
  status: 'draft' | 'approved';
  approved_by: string;
  review_date: string | null;
  created_at: string;
  approved_at: string | null;
}

export interface PupilRow extends Pupil {
  records: number;
  last_record: string | null;
}

export interface PupilDetail extends Pupil {
  records: RecordRow[];
}

export interface Meta {
  need_areas: { key: string; label: string }[];
  needs: { key: string; label: string; area: string }[];
  statuses: string[];
  ai: boolean;
  code_of_practice: string;
}

export interface Adaptation {
  title: string;
  objective: string;
  instructions: string[];
  tasks: { task: string; scaffold: string; steps: string[] }[];
  word_bank: { word: string; meaning: string }[];
  strategies: { strategy: string; why: string }[];
  check: string[];
  sources: Source[];
  needs: string[];
  id?: string;
  pupil_code?: string | null;
}

export interface Period {
  n: number;
  subject: string;
  time: string;
  learn: string;
  video_url: string;
  video_title: string;
  breakdown: Supports | null;
}

export interface DayPlan {
  pupil_id: string;
  code: string;
  phase: string;
  day: string;
  periods: Period[];
}

export interface HelpRequest {
  id: string;
  pupil_id: string;
  code: string;
  period: number | null;
  message: string;
  kind: 'help' | 'safeguarding' | 'finished';
  seen: number;
  created_at: string;
}

@Injectable({ providedIn: 'root' })
export class SenService {
  private readonly http = inject(HttpClient);
  meta(): Observable<Meta> {
    return this.http.get<Meta>('/api/sen/meta');
  }
  demo(): Observable<PupilRow[]> {
    return this.http.post<PupilRow[]>('/api/sen/demo', {});
  }
  demoNote(): Observable<{ code: string; note: string }> {
    return this.http.get<{ code: string; note: string }>('/api/sen/demo/note');
  }
  pupils(): Observable<PupilRow[]> {
    return this.http.get<PupilRow[]>('/api/sen/pupils');
  }
  docs(): Observable<{ id: string; name: string; words: number }[]> {
    return this.http.get<{ id: string; name: string; words: number }[]>('/api/sen/docs');
  }
  pupil(id: string): Observable<PupilDetail> {
    return this.http.get<PupilDetail>(`/api/sen/pupils/${id}`);
  }
  createPupil(p: Partial<Pupil>): Observable<Pupil> {
    return this.http.post<Pupil>('/api/sen/pupils', p);
  }
  updatePupil(id: string, p: Partial<Pupil>): Observable<Pupil> {
    return this.http.patch<Pupil>(`/api/sen/pupils/${id}`, p);
  }
  logSupport(id: string, note: string): Observable<RecordRow> {
    return this.http.post<RecordRow>(`/api/sen/pupils/${id}/records`, { note });
  }
  approveRecord(id: string, record: ApdrRecord, approved_by: string, review_date: string | null): Observable<RecordRow> {
    return this.http.post<RecordRow>(`/api/sen/records/${id}/approve`, { record, approved_by, review_date });
  }
  adaptation(id: string): Observable<Adaptation> {
    return this.http.get<Adaptation>(`/api/sen/adaptations/${id}`);
  }
  adapt(body: { work: string; needs: string[]; pupil_id?: string; phase?: string }): Observable<Adaptation> {
    return this.http.post<Adaptation>('/api/sen/adapt', body);
  }
  extract(file: File): Observable<{ name: string; text: string }> {
    const fd = new FormData();
    fd.append('file', file);
    return this.http.post<{ name: string; text: string }>('/api/sen/extract', fd);
  }
  uploadDoc(file: File): Observable<unknown> {
    const fd = new FormData();
    fd.append('file', file);
    return this.http.post('/api/sen/docs', fd);
  }
  deleteDoc(id: string): Observable<unknown> {
    return this.http.delete(`/api/sen/docs/${id}`);
  }
  day(pupilId: string): Observable<DayPlan> {
    return this.http.get<DayPlan>(`/api/sen/pupils/${pupilId}/day`);
  }
  saveDay(pupilId: string, periods: Partial<Period>[]): Observable<DayPlan> {
    return this.http.put<DayPlan>(`/api/sen/pupils/${pupilId}/day`, { periods });
  }
  help(): Observable<HelpRequest[]> {
    return this.http.get<HelpRequest[]>('/api/sen/help');
  }
  helpSeen(id: string): Observable<unknown> {
    return this.http.post(`/api/sen/help/${id}/seen`, {});
  }
  supports(topic: string, details: string, level: string): Observable<Supports> {
    return this.http.post<Supports>('/api/supports', { topic, details, level });
  }
}
