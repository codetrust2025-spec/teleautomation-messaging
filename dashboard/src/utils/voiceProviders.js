export function browserVoiceCapabilities() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition
  return {mode:Recognition?'browser-half-duplex':'text-only',recognition:Boolean(Recognition),synthesis:Boolean(window.speechSynthesis&&window.SpeechSynthesisUtterance)}
}

const devLog=(event,data={})=>{if(import.meta.env.DEV)console.debug('[VOICE]',{event,at:Date.now(),...data})}

export function createBrowserVoiceProvider(callbacks={}) {
  const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition
  let recognition=null,stream=null,context=null,analyser=null,animation=0,restartTimer=0,activeUtterance=null,speechPoll=0,speechWatchdog=0,speechStallTimer=0,finalizeTimer=0,pendingInterim=''
  let sessionActive=false,recognitionRunning=false,muted=false,speaking=false,processing=false,stopping=false,language='en-IN',turnId=0,speakerGuardUntil=0

  const shouldListen=()=>sessionActive&&!muted&&!speaking&&!processing&&!stopping
  const canListen=()=>shouldListen()&&Date.now()>=speakerGuardUntil
  const clearRestart=()=>{if(restartTimer){clearTimeout(restartTimer);restartTimer=0}}
  const clearFinalize=()=>{if(finalizeTimer){clearTimeout(finalizeTimer);finalizeTimer=0}}
  const clearSpeechTimers=()=>{if(speechPoll){clearInterval(speechPoll);speechPoll=0}if(speechWatchdog){clearTimeout(speechWatchdog);speechWatchdog=0}if(speechStallTimer){clearTimeout(speechStallTimer);speechStallTimer=0}}
  function clearHandlers(){if(!recognition)return;recognition.onstart=null;recognition.onresult=null;recognition.onend=null;recognition.onerror=null;recognition.onspeechstart=null;recognition.onspeechend=null}
  function stopRecognition(abort=false){clearRestart();if(!recognition||!recognitionRunning)return;try{abort?recognition.abort():recognition.stop()}catch{}recognitionRunning=false;devLog('RECOGNITION_STOPPED')}
  function scheduleRecognitionRestart(delay=0){
    clearRestart();if(!shouldListen())return
    const wait=Math.max(delay,speakerGuardUntil-Date.now(),0)
    restartTimer=setTimeout(()=>{restartTimer=0;if(!shouldListen()||recognitionRunning)return;if(!canListen()){scheduleRecognitionRestart(speakerGuardUntil-Date.now());return}try{clearHandlers();const next=new Recognition();next.continuous=true;next.interimResults=true;next.lang=language;recognition=next;attachHandlers(next);next.start()}catch{scheduleRecognitionRestart(300)}},wait)
  }
  function beginTurn(){turnId+=1;callbacks.onInterim?.('');devLog('TURN_CREATED',{turnId});return turnId}
  function submitTranscript(text){
    const finalText=String(text||'').replace(/\s+/g,' ').trim();if(!finalText||processing)return
    clearFinalize();pendingInterim='';const id=beginTurn();processing=true;callbacks.onInterim?.('');callbacks.onState?.('processing');stopRecognition(false);devLog('FINAL_TRANSCRIPT',{turnId:id});callbacks.onFinal?.(finalText,id)
  }
  function scheduleInterimFinalization(delay=1000){clearFinalize();if(!pendingInterim||processing)return;finalizeTimer=setTimeout(()=>{finalizeTimer=0;if(canListen()&&pendingInterim)submitTranscript(pendingInterim)},delay)}
  function meter(){if(!analyser||!sessionActive)return;const values=new Uint8Array(analyser.frequencyBinCount);analyser.getByteFrequencyData(values);callbacks.onLevel?.(values.reduce((a,b)=>a+b,0)/Math.max(1,values.length)/255);animation=requestAnimationFrame(meter)}
  function attachHandlers(instance){
    instance.onstart=()=>{if(recognition!==instance)return;recognitionRunning=true;callbacks.onInterim?.('');callbacks.onState?.('listening');devLog('RECOGNITION_STARTED')}
    instance.onspeechstart=()=>{if(recognition!==instance||!canListen())return;clearFinalize();callbacks.onState?.('speech_detected')}
    instance.onspeechend=()=>{if(recognition!==instance||!canListen())return;scheduleInterimFinalization(450)}
    instance.onresult=event=>{
      if(recognition!==instance)return
      if(!canListen()){devLog('RESULT_IGNORED_DURING_AI_SPEECH');return}
      let interim='',finalChunk=''
      for(let i=event.resultIndex;i<event.results.length;i+=1){const text=event.results[i][0]?.transcript?.trim()||'';if(event.results[i].isFinal)finalChunk+=` ${text}`;else interim+=` ${text}`}
      interim=interim.replace(/\s+/g,' ').trim();finalChunk=finalChunk.replace(/\s+/g,' ').trim()
      if(interim)pendingInterim=interim
      callbacks.onInterim?.(interim||pendingInterim);devLog('RECOGNITION_RESULT',{hasInterim:Boolean(interim),hasFinal:Boolean(finalChunk)})
      if(finalChunk)submitTranscript(finalChunk);else if(pendingInterim)scheduleInterimFinalization(1200)
    }
    instance.onerror=event=>{if(recognition!==instance)return;recognitionRunning=false;if(event.error==='no-speech'||event.error==='aborted'){if(canListen())scheduleRecognitionRestart(250);return}callbacks.onError?.(event.error==='not-allowed'?'Microphone access is blocked. Please allow microphone access in your browser settings.':`Speech recognition error: ${event.error}`)}
    instance.onend=()=>{if(recognition!==instance)return;recognitionRunning=false;if(pendingInterim&&!processing){scheduleInterimFinalization(100)}else if(canListen())scheduleRecognitionRestart(250)}
  }
  async function start(options={}){
    if(!Recognition)throw new Error('Speech recognition is unavailable in this browser.')
    if(sessionActive)return
    language=options.language||language;stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}})
    context=new(window.AudioContext||window.webkitAudioContext)();analyser=context.createAnalyser();analyser.fftSize=256;context.createMediaStreamSource(stream).connect(analyser)
    recognition=null;pendingInterim='';clearFinalize();sessionActive=true;stopping=false;processing=false;speaking=false;meter();scheduleRecognitionRestart(0)
  }
  function setProcessing(value){processing=Boolean(value);if(processing){callbacks.onInterim?.('');stopRecognition(false)}else if(!speaking){speakerGuardUntil=Date.now()+500;scheduleRecognitionRestart(500)}}
  function setMuted(value){muted=Boolean(value);if(muted){callbacks.onInterim?.('');stopRecognition(true);callbacks.onState?.('muted')}else if(sessionActive&&!processing&&!speaking){callbacks.onState?.('listening');scheduleRecognitionRestart(0)}}
  function finishSpeech(token){if(activeUtterance!==token)return;clearSpeechTimers();activeUtterance=null;speaking=false;processing=false;speakerGuardUntil=Date.now()+550;callbacks.onSpeechEnd?.();devLog('AI_SPEECH_ENDED');scheduleRecognitionRestart(550)}
  function speak(text,options={}){
    callbacks.onInterim?.('');processing=false;speaking=true;stopRecognition(true);clearRestart();speakerGuardUntil=Date.now()+Math.max(1500,String(text||'').length*85)
    window.speechSynthesis?.cancel()
    if(!window.speechSynthesis||options.muted||!text){speaking=false;speakerGuardUntil=Date.now()+550;callbacks.onSpeechEnd?.();scheduleRecognitionRestart(550);return}
    const utterance=new SpeechSynthesisUtterance(text);activeUtterance=utterance;utterance.lang=options.language||language;utterance.rate=Number(options.rate||1);let speechStarted=false
    const voices=window.speechSynthesis.getVoices(),lang=utterance.lang.slice(0,2).toLowerCase(),matches=voices.filter(v=>v.lang.toLowerCase().startsWith(lang));const preferred=options.voice==='female'?/female|zira|samantha|heera/i:options.voice==='male'?/male|david|ravi/i:null;utterance.voice=(preferred&&matches.find(v=>preferred.test(v.name)))||matches[0]||null
    const armStallRecovery=()=>{if(speechStallTimer)clearTimeout(speechStallTimer);speechStallTimer=setTimeout(()=>{if(activeUtterance===utterance&&speechStarted){devLog('AI_SPEECH_STALL_RECOVERED');window.speechSynthesis?.cancel();finishSpeech(utterance)}},Math.max(3000,4000/Math.max(.5,utterance.rate)))}
    utterance.onstart=()=>{if(activeUtterance!==utterance)return;speechStarted=true;armStallRecovery();callbacks.onState?.('speaking');devLog('AI_SPEECH_STARTED')}
    utterance.onboundary=()=>{if(activeUtterance===utterance)armStallRecovery()}
    utterance.onend=()=>finishSpeech(utterance)
    utterance.onerror=()=>{if(activeUtterance!==utterance)return;callbacks.onSpeechError?.('Voice output is temporarily unavailable. The response is still available as text.');finishSpeech(utterance)}
    window.speechSynthesis.speak(utterance)
    speechPoll=setInterval(()=>{if(activeUtterance!==utterance){clearSpeechTimers();return}if(speechStarted&&!window.speechSynthesis.speaking&&!window.speechSynthesis.pending){devLog('AI_SPEECH_END_RECOVERED');finishSpeech(utterance)}},250)
    const words=String(text||'').trim().split(/\s+/).filter(Boolean).length
    const maximumDuration=Math.min(40000,Math.max(5000,(words/2/Math.max(.5,utterance.rate))*1000+3500))
    speechWatchdog=setTimeout(()=>{if(activeUtterance===utterance){devLog('AI_SPEECH_WATCHDOG');window.speechSynthesis?.cancel();finishSpeech(utterance)}},maximumDuration)
  }
  function stopSpeech(){const token=activeUtterance;clearSpeechTimers();activeUtterance=null;window.speechSynthesis?.cancel();speaking=false;processing=false;speakerGuardUntil=Date.now()+550;if(token)callbacks.onSpeechEnd?.();scheduleRecognitionRestart(550)}
  function stop(){sessionActive=false;stopping=true;clearRestart();clearFinalize();pendingInterim='';clearSpeechTimers();activeUtterance=null;window.speechSynthesis?.cancel();stopRecognition(true);clearHandlers();stream?.getTracks().forEach(t=>t.stop());if(animation)cancelAnimationFrame(animation);context?.close?.();recognition=null;stream=null;analyser=null;context=null;processing=false;speaking=false;callbacks.onInterim?.('')}
  return {start,stop,speak,stopSpeech,setMuted,setProcessing,capabilities:browserVoiceCapabilities()}
}
