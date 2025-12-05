// Main client-side JS for index.html
// Handles stream fallback, recording, and loading grouped videos

// Stream fallback handling
(function(){
  const img = document.getElementById('mjpeg');
  const iframe = document.getElementById('mjpeg_iframe');
  const status = document.getElementById('status');

  function showStreaming() {
    if (status) status.textContent = 'Streaming';
    img.style.display = '';
    iframe.style.display = 'none';
  }

  function showFallback() {
    if (status) status.textContent = 'Using iframe fallback';
    img.style.display = 'none';
    iframe.style.display = 'block';
  }

  img.addEventListener('load', function(){ showStreaming(); });
  img.addEventListener('error', function(){ showFallback(); });

  setTimeout(function(){
    if (img.complete === false) {
      showFallback();
    }
  }, 4000);
  
  // Safari sometimes renders the MJPEG <img> zoomed on reload. To avoid
  // that, explicitly size the img to 'contain' using its intrinsic aspect
  // ratio and the container dimensions. We update on load and resize.
  function adjustStreamFit() {
    try {
      if (!img || !img.naturalWidth) return;
      const container = img.parentElement;
      if (!container) return;
      const cW = container.clientWidth;
      const cH = container.clientHeight;
      const iW = img.naturalWidth;
      const iH = img.naturalHeight;
      if (!cW || !cH || !iW || !iH) return;
      const cRatio = cW / cH;
      const iRatio = iW / iH;
      if (iRatio > cRatio) {
        // image is wider than container -> fit width
        img.style.width = '100%';
        img.style.height = 'auto';
      } else {
        // image is taller -> fit height
        img.style.width = 'auto';
        img.style.height = '100%';
      }
      // Center the image inside absolute container
      img.style.top = '50%';
      img.style.left = '50%';
      img.style.transform = 'translate(-50%, -50%)';
    } catch (e) {
      // ignore
    }
  }

  if (img) {
    img.addEventListener('load', adjustStreamFit);
    window.addEventListener('resize', adjustStreamFit);
    // try a few times in case the multipart stream takes time to populate dimensions
    let attempts = 0;
    const iv = setInterval(()=>{
      attempts += 1;
      adjustStreamFit();
      if (img.naturalWidth || attempts > 10) clearInterval(iv);
    }, 300);
  }
})();

// Movement polling: poll /movement every 1s and show a message when movement is detected
(function(){
  const el = document.getElementById('movementStatus');
  if (!el) return;

  // Prefer EventSource (SSE) to receive movement updates only when state changes.
  if (window.EventSource) {
    try {
      const es = new EventSource('/movement/stream');
      es.addEventListener('message', (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (data.movement) {
            el.style.display = 'block';
          } else {
            el.style.display = 'none';
          }
        } catch (e) {
          el.style.display = 'none';
        }
      });
      es.addEventListener('error', () => {
        // On error, hide indicator to avoid stale UI and close EventSource
        el.style.display = 'none';
        try { es.close(); } catch (e) {}
      });
      // Graceful close on page unload
      window.addEventListener('beforeunload', ()=> { try { es.close(); } catch(e){} });
    } catch (e) {
      // Fall back to polling below
      startPollingFallback(el);
    }
  } else {
    // Browser doesn't support EventSource -> polling fallback
    startPollingFallback(el);
  }

  function startPollingFallback(el){
    let visibleOnly = true;
    async function poll(){
      try{
        if (visibleOnly && document && document.hidden) return;
        const r = await fetch('/movement');
        if (!r.ok) throw new Error('network');
        const j = await r.json();
        const mov = !!j.movement;
        el.style.display = mov ? 'block' : 'none';
      }catch(e){
        el.style.display = 'none';
      }
    }
    poll();
    setInterval(poll, 3000); // slower polling as a fallback
  }
})();

// Recording UI
(function(){
  const btn = document.getElementById('recordBtn');
  const status = document.getElementById('recordStatus');
  const linkBox = document.getElementById('recordingLink');

  async function startRecord(){
    status.textContent = 'Starting...';
    btn.disabled = true;
    linkBox.innerHTML = '';
    try{
      const resp = await fetch('/record', { method: 'POST' });
      if (!resp.ok) throw new Error('busy');
      const data = await resp.json();
      status.textContent = `Recording ${data.duration}s...`;
      setTimeout(async ()=>{
        status.textContent = 'Finalizing...';
        const r = await fetch('/last_recording');
        const j = await r.json();
        if (j.filename){
          const a = document.createElement('a');
          a.href = '/recordings/' + encodeURIComponent(j.filename);
          a.textContent = 'Download: ' + j.filename;
          linkBox.appendChild(a);
          status.textContent = 'Recording ready';
        } else {
          status.textContent = 'No recording found';
        }
        btn.disabled = false;
      }, (10 + 1) * 1000);
    }catch(e){
      status.textContent = 'Recorder busy';
      btn.disabled = false;
    }
  }

  btn.addEventListener('click', startRecord);
})();

// Video list UI (grouped by date)
(function(){
  const videoList = document.getElementById('videoList');

  async function loadVideos(){
    videoList.innerHTML = '<p style="color:#888;">Loading videos...</p>';
    try{
      const resp = await fetch('/videos/grouped');
      if (!resp.ok) throw new Error('Failed to fetch');
      const groups = await resp.json();

      if (!Array.isArray(groups) || groups.length === 0){
        videoList.innerHTML = '<p style="color:#888;">No videos yet</p>';
        return;
      }

      let html = '';
      groups.forEach(group => {
        const dateLabel = group.date === 'unknown' ? 'Unknown date' : new Date(group.date).toLocaleDateString();
        const count = Array.isArray(group.videos) ? group.videos.length : 0;
        const plural = count === 1 ? 'video' : 'videos';
        html += `<div style="margin-bottom:12px;">
          <button class="date-btn" aria-expanded="false">${dateLabel} (${count} ${plural})</button>
            <div class="group-videos" style="display:none;">
              <ul style="list-style:none;padding:0;margin:8px 0 0 0;">
        `;

          group.videos.forEach(v => {
          const date = v.created_at ? new Date(v.created_at).toLocaleString() : '';
          const size = v.size ? (v.size / (1024*1024)).toFixed(2) : '0.00';
            const streamUrl = (v.url && v.url.startsWith('http')) ? v.url : (`/recordings/${encodeURIComponent(v.filename)}`);
          html += `
                <li class="video-entry">
                  <div><strong>${v.filename}</strong></div>
                  <div style="font-size:0.9em;color:#aaa;">${date} • ${size} MB</div>
                  <div style="margin-top:8px;">
                    <a href="${streamUrl}" class="btn stream-link" data-filename="${encodeURIComponent(v.filename)}">Stream</a>
                    <a href="${streamUrl}" class="btn download-link" download="${v.filename}">Download</a>
                  </div>
                </li>
          `;
        });

        html += '</ul></div></div>';
      });

      videoList.innerHTML = html;

      document.querySelectorAll('#videoList .date-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          const list = btn.nextElementSibling;
          if (!list) return;
          const isHidden = list.style.display === 'none' || list.style.display === '';
          list.style.display = isHidden ? 'block' : 'none';
          btn.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
        });
      });

      // Hook stream links to open modal player
      function openModalPlayer(src, filename) {
        const modal = document.getElementById('videoModal');
        const content = document.getElementById('videoModalContent');
        if (!modal || !content) return;
        // Clear previous content
        content.innerHTML = '';
        const video = document.createElement('video');
        video.controls = true;
        video.autoplay = true;
        video.src = src;
        video.setAttribute('playsinline', '');
        content.appendChild(video);
        const close = document.createElement('button');
        close.id = 'videoModalClose';
        close.textContent = 'Close';
        close.addEventListener('click', ()=>{ video.pause(); modal.style.display = 'none'; content.innerHTML = ''; });
        content.appendChild(close);
        modal.style.display = 'flex';
      }

      document.querySelectorAll('#videoList a.stream-link').forEach(a => {
        a.addEventListener('click', (e) => {
          e.preventDefault();
          const src = a.href;
          openModalPlayer(src, a.dataset.filename || 'video');
        });
      });

      // Close modal when clicking outside content
      const modalEl = document.getElementById('videoModal');
      if (modalEl) {
        modalEl.addEventListener('click', (e)=>{
          if (e.target === modalEl) {
            const content = document.getElementById('videoModalContent');
            if (content) { content.innerHTML = ''; }
            modalEl.style.display = 'none';
          }
        });
      }

    }catch(e){
      videoList.innerHTML = '<p style="color:#f55;">Failed to load videos</p>';
      console.error(e);
    }
  }

  // Load videos once on page load. Removed manual refresh button and auto-refresh.
  loadVideos();
})();
