import type { ReactNode } from 'react';

export default function LearningPageHeader({ title, description, children }: { title: string; description: string; children?: ReactNode }) {
  return <header className="learning-page-header"><div><h1>{title}</h1><p className="lead">{description}</p></div>{children && <div className="learning-page-header__actions">{children}</div>}</header>;
}
