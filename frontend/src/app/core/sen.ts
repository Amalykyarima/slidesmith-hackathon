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

export interface Attendance {
  pct: number;
  recent_pct: number | null;
  flag: 'ok' | 'watch' | 'persistent';
  updated_at: string;
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

export interface DraftDoc {
  id: string;
  kind: 'support_plan' | 'ehcp_contribution' | 'parent_update';
  kind_label: string;
  title: string;
  body: string;
  checks: string[];
  sources: Source[];
  status: 'draft' | 'signed';
  signed_by: string;
  signed_at: string | null;
  created_at: string;
}

export interface PupilDetail extends Pupil {
  records: RecordRow[];
  drafts: DraftDoc[];
  attendance: Attendance | null;
}

export interface DashRow extends Pupil {
  attendance: Attendance | null;
  review_state: 'overdue' | 'soon' | 'ok' | 'none';
  records: number;
  unapproved: number;
  last_record: string | null;
}

export interface Dashboard {
  pupils: DashRow[];
  counts: Record<'pupils' | 'sen_support' | 'ehcp' | 'overdue' | 'soon' | 'attendance_flags' | 'unapproved' | 'unsigned', number>;
  by_area: Record<string, number>;
  provision: { name: string; pupils: number }[];
  docs: { id: string; name: string; words: number }[];
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
}

@Injectable({ providedIn: 'root' })
export class SenService {
  private readonly http = inject(HttpClient);
  meta(): Observable<Meta> {
    return this.http.get<Meta>('/api/sen/meta');
  }
  dashboard(): Observable<Dashboard> {
    return this.http.get<Dashboard>('/api/sen/dashboard');
  }
  demo(): Observable<Dashboard> {
    return this.http.post<Dashboard>('/api/sen/demo', {});
  }
  demoNote(): Observable<{ code: string; note: string }> {
    return this.http.get<{ code: string; note: string }>('/api/sen/demo/note');
  }
  pupils(): Observable<Pupil[]> {
    return this.http.get<Pupil[]>('/api/sen/pupils');
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
  draft(id: string, kind: DraftDoc['kind']): Observable<DraftDoc> {
    return this.http.post<DraftDoc>(`/api/sen/pupils/${id}/drafts`, { kind });
  }
  editDraft(id: string, body: string): Observable<DraftDoc> {
    return this.http.patch<DraftDoc>(`/api/sen/drafts/${id}`, { body });
  }
  signDraft(id: string, body: string, signed_by: string): Observable<DraftDoc> {
    return this.http.post<DraftDoc>(`/api/sen/drafts/${id}/sign`, { body, signed_by });
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
  uploadAttendance(file: File): Observable<{ rows: number }> {
    const fd = new FormData();
    fd.append('file', file);
    return this.http.post<{ rows: number }>('/api/sen/attendance', fd);
  }
  supports(topic: string, details: string, level: string): Observable<Supports> {
    return this.http.post<Supports>('/api/supports', { topic, details, level });
  }
}

/** Tiny, safe Markdown for drafts: headings, bullets, bold, citations. Escapes everything first. */
export function mdToHtml(md: string): string {
  const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const inline = (s: string) =>
    esc(s)
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\[(to add:[^\]]*)\]/g, '<mark>[$1]</mark>')
      .replace(/\[([CS]\d+)\]/g, '<sup class="cite">$1</sup>');
  const out: string[] = [];
  let list = false;
  for (const raw of (md || '').split('\n')) {
    const line = raw.trimEnd();
    const bullet = /^\s*[-*]\s+(.*)/.exec(line);
    if (!bullet && list) {
      out.push('</ul>');
      list = false;
    }
    if (bullet) {
      if (!list) out.push('<ul>');
      list = true;
      out.push(`<li>${inline(bullet[1])}</li>`);
    } else if (/^#{1,3}\s/.test(line)) {
      out.push(`<h4>${inline(line.replace(/^#+\s*/, ''))}</h4>`);
    } else if (line.trim()) {
      out.push(`<p>${inline(line)}</p>`);
    }
  }
  if (list) out.push('</ul>');
  return out.join('');
}
