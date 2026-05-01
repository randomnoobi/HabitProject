/* ========================================
   DESK TALK — Website Interactivity
   ======================================== */

// ═══ Scroll-triggered reveal animations ═══
const revealEls = document.querySelectorAll('.reveal');
const observer = new IntersectionObserver((entries) => {
  entries.forEach((entry, i) => {
    if (entry.isIntersecting) {
      setTimeout(() => entry.target.classList.add('visible'), i * 80);
      observer.unobserve(entry.target);
    }
  });
}, { threshold: 0.15, rootMargin: '0px 0px -40px 0px' });
revealEls.forEach(el => observer.observe(el));

// ═══ Nav scroll effect ═══
const nav = document.querySelector('.nav');
window.addEventListener('scroll', () => {
  nav.classList.toggle('scrolled', window.scrollY > 60);
}, { passive: true });

// ═══ Smooth scroll for nav links ═══
document.querySelectorAll('a[href^="#"]').forEach(link => {
  link.addEventListener('click', (e) => {
    const target = document.querySelector(link.getAttribute('href'));
    if (target) {
      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
});

// ═══ Mobile nav toggle ═══
const navToggle = document.querySelector('.nav-toggle');
const navEl = document.querySelector('.nav');
if (navToggle && navEl) {
  navToggle.addEventListener('click', () => {
    const open = navEl.classList.toggle('nav-open');
    navToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  navEl.querySelectorAll('.nav-links a[href^="#"]').forEach((a) => {
    a.addEventListener('click', () => {
      navEl.classList.remove('nav-open');
      navToggle.setAttribute('aria-expanded', 'false');
    });
  });
}

// ═══ Scroll spy: nav + Contents sidebar + read progress bar ═══
const SECTION_ORDER = [
  'hero', 'concept-video', 'problem', 'concept', 'hardware', 'pipeline',
  'characters', 'relationships', 'demo', 'contact',
];

function updateScrollUi() {
  const scrollY = window.scrollY;
  const marker = scrollY + Math.min(160, window.innerHeight * 0.22);
  let activeId = SECTION_ORDER[0];
  for (const id of SECTION_ORDER) {
    const el = document.getElementById(id);
    if (!el) continue;
    const top = el.getBoundingClientRect().top + scrollY;
    if (top <= marker) activeId = id;
  }

  document.querySelectorAll('.nav-links a[href^="#"]').forEach(link => {
    const id = link.getAttribute('href').slice(1);
    link.classList.toggle('nav-link-active', id === activeId);
  });

  document.querySelectorAll('.site-contents-list a[data-contents]').forEach(link => {
    const id = link.getAttribute('href').slice(1);
    link.classList.toggle('is-active', id === activeId);
  });

  const contentsBar = document.querySelector('.site-contents-progress-bar');
  if (contentsBar) {
    const doc = document.documentElement;
    const maxScroll = Math.max(1, doc.scrollHeight - doc.clientHeight);
    contentsBar.style.width = `${Math.min(100, Math.max(0, (scrollY / maxScroll) * 100))}%`;
  }
}

window.addEventListener('scroll', updateScrollUi, { passive: true });
window.addEventListener('resize', updateScrollUi, { passive: true });
updateScrollUi();

// ═══ Staggered reveal for grids ═══
document.querySelectorAll('.concept-grid, .char-grid').forEach(grid => {
  const gridObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const children = entry.target.querySelectorAll('.reveal');
        children.forEach((child, i) => {
          setTimeout(() => child.classList.add('visible'), i * 100);
        });
        gridObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.1 });
  gridObserver.observe(grid);
});

// ═══ SHOWCASE — Full-screen parallax sections ═══
const showcases = document.querySelectorAll('.showcase');

function updateShowcaseParallax() {
  const scrollY = window.scrollY;
  const windowH = window.innerHeight;

  showcases.forEach(section => {
    const rect = section.getBoundingClientRect();
    const speed = parseFloat(section.dataset.speed) || 0.4;

    if (rect.bottom < -200 || rect.top > windowH + 200) return;

    const progress = (windowH - rect.top) / (windowH + rect.offsetHeight);
    const yOffset = (progress - 0.5) * rect.offsetHeight * speed;
    const bg = section.querySelector('.showcase-bg');
    if (bg) bg.style.transform = `translateY(${yOffset}px)`;
  });
}

window.addEventListener('scroll', updateShowcaseParallax, { passive: true });
window.addEventListener('resize', updateShowcaseParallax, { passive: true });
updateShowcaseParallax();


// ═══ CAROUSEL — Demo gallery ═══
(function initCarousel() {
  const track = document.querySelector('.carousel-track');
  if (!track) return;

  const slides = Array.from(track.querySelectorAll('.carousel-slide'));
  const dots   = Array.from(document.querySelectorAll('.carousel-dot'));
  const prevBtn = document.querySelector('.carousel-prev');
  const nextBtn = document.querySelector('.carousel-next');
  const progressBar = document.querySelector('.carousel-progress-bar');

  let current  = 0;
  let autoTimer = null;
  let progressTimer = null;
  const INTERVAL = 6000;
  const PROGRESS_STEP = 50;
  let progressElapsed = 0;
  let direction = 1; // 1 = forward, -1 = backward

  function goTo(idx, dir) {
    if (idx === current) return;
    direction = dir !== undefined ? dir : (idx > current ? 1 : -1);

    const leaving = slides[current];
    const entering = slides[idx];

    leaving.classList.remove('active');
    leaving.classList.add(direction > 0 ? 'exit-left' : 'exit-right');

    entering.classList.remove('exit-left', 'exit-right');
    entering.classList.add('active');

    setTimeout(() => {
      leaving.classList.remove('exit-left', 'exit-right');
    }, 900);

    dots.forEach(d => d.classList.remove('active'));
    if (dots[idx]) dots[idx].classList.add('active');

    current = idx;
    resetProgress();
  }

  function next() { goTo((current + 1) % slides.length, 1); }
  function prev() { goTo((current - 1 + slides.length) % slides.length, -1); }

  function resetProgress() {
    progressElapsed = 0;
    if (progressBar) progressBar.style.width = '0%';
  }

  function startAuto() {
    stopAuto();
    progressElapsed = 0;
    progressTimer = setInterval(() => {
      progressElapsed += PROGRESS_STEP;
      const pct = Math.min((progressElapsed / INTERVAL) * 100, 100);
      if (progressBar) progressBar.style.width = pct + '%';
      if (progressElapsed >= INTERVAL) {
        next();
      }
    }, PROGRESS_STEP);
  }

  function stopAuto() {
    clearInterval(progressTimer);
    progressTimer = null;
  }

  function pauseOnHover() {
    const carousel = document.querySelector('.carousel');
    if (!carousel) return;
    carousel.addEventListener('mouseenter', stopAuto);
    carousel.addEventListener('mouseleave', startAuto);
  }

  if (prevBtn) prevBtn.addEventListener('click', () => { prev(); startAuto(); });
  if (nextBtn) nextBtn.addEventListener('click', () => { next(); startAuto(); });

  dots.forEach(dot => {
    dot.addEventListener('click', () => {
      const idx = parseInt(dot.dataset.idx, 10);
      if (!isNaN(idx)) { goTo(idx); startAuto(); }
    });
  });

  // Keyboard navigation
  document.addEventListener('keydown', (e) => {
    const carousel = document.querySelector('.carousel');
    if (!carousel) return;
    const rect = carousel.getBoundingClientRect();
    const inView = rect.top < window.innerHeight && rect.bottom > 0;
    if (!inView) return;

    if (e.key === 'ArrowLeft') { prev(); startAuto(); }
    if (e.key === 'ArrowRight') { next(); startAuto(); }
  });

  // Touch swipe support
  let touchStartX = 0;
  track.addEventListener('touchstart', (e) => {
    touchStartX = e.changedTouches[0].screenX;
    stopAuto();
  }, { passive: true });
  track.addEventListener('touchend', (e) => {
    const diff = touchStartX - e.changedTouches[0].screenX;
    if (Math.abs(diff) > 50) {
      diff > 0 ? next() : prev();
    }
    startAuto();
  }, { passive: true });

  pauseOnHover();

  // Start auto-play only when carousel is in viewport
  const carouselObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        startAuto();
      } else {
        stopAuto();
      }
    });
  }, { threshold: 0.3 });

  const carouselEl = document.querySelector('.carousel');
  if (carouselEl) carouselObserver.observe(carouselEl);
})();


// ═══ INLINE VIDEO PLAYER — Play/pause, progress ═══
(function initInlineVideo() {
  const wrapper = document.querySelector('.fullwidth-video .video-wrapper');
  if (!wrapper) return;

  const video   = wrapper.querySelector('.inline-video');
  const overlay = wrapper.querySelector('.video-play-overlay');
  const fill    = wrapper.querySelector('.video-progress-fill');
  if (!video) return;

  function play() {
    video.play();
    if (overlay) overlay.classList.add('hidden');
  }

  function pause() {
    video.pause();
    if (overlay) overlay.classList.remove('hidden');
  }

  if (overlay) overlay.addEventListener('click', play);

  video.addEventListener('click', () => {
    video.paused ? play() : pause();
  });

  video.addEventListener('ended', () => {
    if (overlay) overlay.classList.remove('hidden');
    if (fill) fill.style.width = '0%';
  });

  video.addEventListener('timeupdate', () => {
    if (!fill || !video.duration) return;
    fill.style.width = (video.currentTime / video.duration * 100) + '%';
  });

  const progressTrack = wrapper.querySelector('.video-progress');
  if (progressTrack) {
    progressTrack.addEventListener('click', (e) => {
      const rect = progressTrack.getBoundingClientRect();
      const pct  = (e.clientX - rect.left) / rect.width;
      video.currentTime = pct * video.duration;
    });
  }
})();
