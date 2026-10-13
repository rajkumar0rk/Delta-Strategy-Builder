import {describe,expect,it} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {ResearchJobProgress} from './ReplayResearchPanel';
import type {JobState} from '../types';

const job=(patch:Partial<JobState>={}):JobState=>({
 id:'job-1',status:'RUNNING',message:'Execution scenario (3/8): Evaluated candles',
 stage:'EXECUTION_REPLAY',progress_percent:36.5,next_step:'Next scenario',...patch,
});

describe('V16 research job progress',()=>{
 it('renders actual server progress, current stage and Stop action',()=>{
  const markup=renderToStaticMarkup(<ResearchJobProgress job={job()} onStop={()=>{}}/>);
  expect(markup).toContain('EXECUTION_REPLAY');
  expect(markup).toContain('37%');
  expect(markup).toContain('Execution scenario (3/8)');
  expect(markup).toContain('Next scenario');
  expect(markup).toContain('Stop research');
  expect(markup).toContain('value="36.5"');
 });
 it('shows holdout work and disables Stop after cancellation request',()=>{
  const markup=renderToStaticMarkup(<ResearchJobProgress job={job({
   status:'CANCELLING',stage:'CANCELLING',progress_percent:75,
   message:'Stop requested'
  })} onStop={()=>{}}/>);
  expect(markup).toContain('75%');
  expect(markup).toContain('Stopping…');
  expect(markup).toContain('disabled');
 });
 it('clamps invalid high progress percentages',()=>{
  const markup=renderToStaticMarkup(<ResearchJobProgress job={job({
   progress_percent:140,status:'COMPLETE',stage:'COMPLETE'
  })} onStop={()=>{}}/>);
  expect(markup).toContain('100%');
  expect(markup).toContain('value="100"');
 });
});
