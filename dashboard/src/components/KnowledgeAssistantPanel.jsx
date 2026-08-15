import React, { useEffect, useRef, useState } from 'react'
import { API } from '../config.js'
import { browserVoiceCapabilities, createBrowserVoiceProvider } from '../utils/voiceProviders.js'
import './knowledgeAssistant.css'

const EXAMPLES = ['Give me a Marketing pipeline briefing.','Which leads have had no reply for two days?','Show leads marked for follow-up.','Summarize a lead status.']
const LANGS = {auto:'en-IN',en:'en-IN',te:'te-IN',hi:'hi-IN'}
const STATUS_TEXT = {idle:'Start speaking when you are ready',connecting:'Connecting…',ready:'Ready',listening:'Listening…',speech_detected:'Listening…',processing:'Understanding your request…',understanding:'Understanding your request…',thinking:'Checking TeleAutomation data…',speaking:'Assistant is speaking',interrupted:'Listening to your update…',paused:'Paused',muted:'Microphone muted',reconnecting:'Reconnecting…',error:'Voice connection error',ended:'Conversation ended'}
const now = () => new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})

function Records({ rows = [] }) {
  const [open, setOpen] = useState(false)
  if (!rows.length) return null
  return <div className="kai-records"><button type="button" onClick={()=>setOpen(v=>!v)} aria-expanded={open}>{open?'Hide':'Show'} supporting records ({rows.length})</button>{open&&<div className="kai-record-grid">{rows.map((r,i)=><article key={`${r.type}-${r.id}-${i}`}><header><strong>{r.title}</strong><span>{r.type}</span></header><p>{r.detail}</p>{r.fields&&<dl>{Object.entries(r.fields).filter(([,v])=>v!==''&&v!=null).map(([k,v])=><div key={k}><dt>{k.replaceAll('_',' ')}</dt><dd>{String(v)}</dd></div>)}</dl>}</article>)}</div>}</div>
}

function Message({ message, onSpeak, onStop }) {
  const assistant = message.role === 'assistant'
  return <article className={`kai-message kai-message--${message.role}${message.speaking?' is-speaking':''}${message.interrupted?' is-interrupted':''}`}>
    <div className="kai-message-head"><span>{assistant?'AI':'You'}</span><time>{message.time}</time></div><p>{message.text}</p>
    {assistant&&<div className="kai-message-actions"><button onClick={()=>onSpeak(message)}>Listen</button><button onClick={onStop}>Stop</button><button onClick={()=>navigator.clipboard?.writeText(message.text)}>Copy</button></div>}
    {assistant&&<Records rows={message.evidence}/>}</article>
}

export function KnowledgeAssistantPanel() {
  const [text,setText]=useState(''), [messages,setMessages]=useState([]), [loading,setLoading]=useState(false), [error,setError]=useState('')
  const [live,setLive]=useState(false), [voiceState,setVoiceState]=useState('idle'), [interim,setInterim]=useState(''), [level,setLevel]=useState(0)
  const [micMuted,setMicMuted]=useState(false), [speakerMuted,setSpeakerMuted]=useState(false), [showTranscript,setShowTranscript]=useState(true), [showType,setShowType]=useState(false), [settings,setSettings]=useState(false)
  const [prefs,setPrefs]=useState(()=>{try{return {...{language:'auto',voice:'default',rate:1,autoSpeak:true},...JSON.parse(localStorage.getItem('teleautomation-ai-voice')||'{}')}}catch{return {language:'auto',voice:'default',rate:1,autoSpeak:true}}})
  const provider=useRef(null), session=useRef(''), aborter=useRef(null), scrollRef=useRef(null), askRef=useRef(null), speechRecovery=useRef(0)
  const requestInFlight=useRef(false), lastSubmittedTranscript=useRef(''), lastSubmittedAt=useRef(0), lastSubmittedTurn=useRef(0), sessionActive=useRef(false)
  const caps=browserVoiceCapabilities()

  useEffect(()=>{ try{localStorage.setItem('teleautomation-ai-voice',JSON.stringify(prefs))}catch{} },[prefs])
  useEffect(()=>()=>cleanup(false),[])
  useEffect(()=>{scrollRef.current?.scrollTo({top:scrollRef.current.scrollHeight,behavior:'smooth'})},[messages,interim])

  async function ask(value, source='text', turnId=0) {
    const question=String(value||'').replace(/\s+/g,' ').trim(); if(!question)return
    const normalized=question.toLowerCase().replace(/[^\p{L}\p{N}\s]/gu,'').replace(/\s+/g,' ').trim()
    const duplicate=normalized&&normalized===lastSubmittedTranscript.current&&Date.now()-lastSubmittedAt.current<8000
    if(requestInFlight.current||duplicate||(turnId&&turnId===lastSubmittedTurn.current))return
    requestInFlight.current=true;lastSubmittedTranscript.current=normalized;lastSubmittedAt.current=Date.now();if(turnId)lastSubmittedTurn.current=turnId
    if(live)provider.current?.setProcessing(true)
    aborter.current?.abort(); const controller=new AbortController(); aborter.current=controller
    setMessages(m=>[...m,{id:crypto.randomUUID(),role:'user',text:question,time:now()}]); setText(''); setInterim(''); setLoading(true); setError(''); setVoiceState(source==='voice'?'understanding':'thinking')
    try{
      const res=await fetch(`${API}/ai/knowledge/query`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,session_id:session.current||undefined}),signal:controller.signal})
      const data=await res.json(); if(!res.ok||data.status!=='ok')throw new Error(data.message||'Assistant query failed')
      session.current=data.session_id||session.current
      const msg={id:crypto.randomUUID(),role:'assistant',text:data.answer,time:now(),evidence:data.evidence||[]}
      setMessages(m=>[...m,msg]); setVoiceState('thinking')
      if(live&&prefs.autoSpeak&&!speakerMuted) speak(msg); else if(live){provider.current?.setProcessing(false)}
    }catch(e){if(e.name!=='AbortError'){setError(e.message||'Connection was interrupted.');setVoiceState('error')}if(live)provider.current?.setProcessing(false)}finally{requestInFlight.current=false;setLoading(false)}
  }
  askRef.current=ask

  function speak(msg){
    if(speechRecovery.current)clearTimeout(speechRecovery.current)
    setMessages(m=>m.map(x=>({...x,speaking:x.id===msg.id})))
    provider.current?.speak(msg.text,{muted:speakerMuted,language:LANGS[prefs.language],voice:prefs.voice,rate:prefs.rate})
    const words=String(msg.text||'').trim().split(/\s+/).filter(Boolean).length
    const recoveryDelay=Math.min(45000,Math.max(6500,(words/2/Math.max(.5,prefs.rate))*1000+4000))
    speechRecovery.current=setTimeout(()=>{
      speechRecovery.current=0
      if(!sessionActive.current)return
      provider.current?.stopSpeech()
      provider.current?.setMuted(false)
      setMicMuted(false)
      setVoiceState('listening')
    },recoveryDelay)
  }
  function stopSpeech(interrupted=false){if(speechRecovery.current){clearTimeout(speechRecovery.current);speechRecovery.current=0}provider.current?.stopSpeech();setMessages(m=>m.map(x=>x.speaking?{...x,speaking:false,interrupted}:x));if(sessionActive.current&&!micMuted)setVoiceState(interrupted?'interrupted':'listening')}

  async function startLive(){
    if(!caps.recognition){setError('Live speech recognition is unavailable in this browser. You can continue using text.');return}
    setLive(true);sessionActive.current=true;setVoiceState('connecting');setError('')
    const p=createBrowserVoiceProvider({onState:setVoiceState,onLevel:setLevel,onInterim:setInterim,onFinal:(t,id)=>askRef.current?.(t,'voice',id),onSpeechEnd:()=>{if(speechRecovery.current){clearTimeout(speechRecovery.current);speechRecovery.current=0}setMessages(m=>m.map(x=>({...x,speaking:false})));if(sessionActive.current&&!micMuted)setVoiceState('listening')},onSpeechError:setError,onError:e=>{setError(e);setVoiceState('error')}})
    provider.current=p
    try{await p.start({language:LANGS[prefs.language]});setVoiceState('listening')}catch(e){setError(e.name==='NotAllowedError'?'Microphone access is blocked. Please allow microphone access in your browser settings.':e.message);setVoiceState('error')}
  }
  function cleanup(end=true){sessionActive.current=false;requestInFlight.current=false;if(speechRecovery.current){clearTimeout(speechRecovery.current);speechRecovery.current=0}aborter.current?.abort();provider.current?.stop();provider.current=null;window.speechSynthesis?.cancel();if(end&&session.current)fetch(`${API}/ai/knowledge/session/${session.current}`,{method:'DELETE'}).catch(()=>{});if(end)session.current='';lastSubmittedTranscript.current='';lastSubmittedTurn.current=0;setLive(false);setVoiceState(end?'ended':'idle');setInterim('')}
  function toggleMic(){
    if(voiceState==='speaking'){
      stopSpeech(true);setMicMuted(false);provider.current?.setMuted(false);setVoiceState('listening');return
    }
    const v=!micMuted;setMicMuted(v);provider.current?.setMuted(v);setVoiceState(v?'muted':'listening')
  }

  return <main className="kai-page"><header className="kai-header"><div><span className="kai-kicker">TELEAUTOMATION</span><h1>TeleAutomation AI Assistant</h1><p>Ask questions using text or start a live voice conversation.</p></div><div className="kai-header-actions"><span className="kai-readonly">● Read-only</span><button className="kai-live-launch" onClick={startLive}>◉ Start Live Conversation</button></div></header>
    <div className="kai-security">TeleAutomation AI can only read authorized data. No records can be changed.</div>
    <div className="kai-prompts" aria-label="Suggested questions">{EXAMPLES.map(x=><button key={x} onClick={()=>ask(x)}>{x}</button>)}</div>
    <section className="kai-chat" ref={scrollRef} aria-live="polite">{!messages.length&&<div className="kai-empty"><div>AI</div><h2>What would you like to know?</h2><p>Ask about leads, follow-ups, reminders and the Marketing pipeline.</p></div>}{messages.map(m=><Message key={m.id} message={m} onSpeak={speak} onStop={()=>stopSpeech(false)}/>)}{loading&&<div className="kai-thinking"><span/><span/><span/> Checking authorized data…</div>}</section>
    {error&&<div className="kai-error" role="alert">{error}<button onClick={()=>setError('')}>Dismiss</button></div>}
    <form className="kai-composer" onSubmit={e=>{e.preventDefault();ask(text)}}><textarea value={text} onChange={e=>setText(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ask(text)}}} placeholder="Ask about TeleAutomation data…" rows={1}/><button type="button" className="kai-mic-shortcut" onClick={startLive} aria-label="Start live voice">◉</button><button disabled={loading||!text.trim()} aria-label="Send question">Send</button></form>
    {live&&<div className="kai-live" role="dialog" aria-modal="true" aria-label="TeleAutomation Live AI Assistant"><header><div><h2>TeleAutomation Live AI</h2><p>Ask about leads, follow-ups, reminders and the Marketing pipeline.</p></div><div><span className="kai-readonly">Read-only</span><span className={`kai-connection kai-connection--${voiceState}`}>● {voiceState}</span><button onClick={()=>setShowTranscript(false)} aria-label="Minimize transcript">—</button><button onClick={()=>cleanup(true)} aria-label="End conversation">×</button></div></header>
      <div className={`kai-live-body${showTranscript?'':' transcript-hidden'}`}><section className="kai-orb-zone"><div className={`kai-orb kai-orb--${voiceState}`} style={{'--level':Math.max(.08,level)}}><div>◉</div></div><h3>{STATUS_TEXT[voiceState]||voiceState}</h3>{interim&&<p className="kai-interim"><span>You are saying:</span> “{interim}”</p>}<small>{caps.mode==='browser-half-duplex'?'Safe browser voice mode':'Text-only fallback'}</small></section>
        {showTranscript&&<section className="kai-live-transcript" ref={scrollRef}>{messages.map(m=><Message key={m.id} message={m} onSpeak={speak} onStop={()=>stopSpeech(false)}/>)}{interim&&<article className="kai-message kai-message--user is-interim"><p>{interim}…</p></article>}</section>}</div>
      {showType&&<form className="kai-live-type" onSubmit={e=>{e.preventDefault();ask(text);setShowType(false)}}><input autoFocus value={text} onChange={e=>setText(e.target.value)} placeholder="Type a question…"/><button>Send</button></form>}
      {settings&&<div className="kai-settings"><label>Language<select value={prefs.language} onChange={e=>setPrefs(p=>({...p,language:e.target.value}))}><option value="auto">Auto Detect</option><option value="en">English</option><option value="te">Telugu</option><option value="hi">Hindi</option></select></label><label>Voice<select value={prefs.voice} onChange={e=>setPrefs(p=>({...p,voice:e.target.value}))}><option value="default">Default</option><option value="female">Female (when available)</option><option value="male">Male (when available)</option></select></label><label>Speed<select value={prefs.rate} onChange={e=>setPrefs(p=>({...p,rate:Number(e.target.value)}))}><option value={.75}>0.75x</option><option value={1}>1x</option><option value={1.25}>1.25x</option></select></label><label><input type="checkbox" checked={prefs.autoSpeak} onChange={e=>setPrefs(p=>({...p,autoSpeak:e.target.checked}))}/> Auto speak</label></div>}
      <footer className="kai-controls"><button className={micMuted?'active':''} onClick={toggleMic} aria-label={micMuted?'Unmute microphone':'Mute microphone'}>🎙<span>{micMuted?'Unmute':'Mic'}</span></button><button className={speakerMuted?'active':''} onClick={()=>{setSpeakerMuted(v=>!v);if(!speakerMuted)stopSpeech(false)}} aria-label="Toggle speaker">🔊<span>Speaker</span></button><button onClick={()=>setShowTranscript(v=>!v)}>☰<span>Transcript</span></button><button onClick={()=>setShowType(v=>!v)}>⌨<span>Type</span></button><button onClick={()=>setSettings(v=>!v)}>⚙<span>Settings</span></button><button className="end" onClick={()=>cleanup(true)}>■<span>End</span></button></footer>
    </div>}
  </main>
}
