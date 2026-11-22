/* Guida luminosa dell'esercizio passo passo: sul passo mostrato nella finestra a destra fa brillare la casella o il
   pulsante da usare adesso e accanto mette una nuvoletta con «COSA STIAMO FACENDO» e «ORA TOCCA A TE».
   Le caselle si trovano dall'etichetta scritta nel passo (es. «Dipendente», «Dal», «Pulsante = Salva»). */
(function () {
  var box = document.getElementById('guida');
  if (!box) return;
  var LS = 'mp-guida-luce', spento = leggi(LS) === '0';
  var bolla = document.createElement('div'); bolla.id = 'gl-bolla'; bolla.hidden = true; document.body.appendChild(bolla);
  var acceso = null, toccati = new WeakSet(), ultimoPasso = -1;

  function leggi(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function scrivi(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]; }); }
  function norm(s) { return String(s || '').toLowerCase().replace(/[«»"“”'’()]/g, ' ').replace(/\s+/g, ' ').trim(); }
  function visibile(el) { return el && el.offsetParent !== null && !box.contains(el); }

  // etichette che descrivono un'azione o una lettura, non una casella
  var NON_CAMPI = /^(menu|dove|apri|leggi|controlla|poi|prima|attenzione|cosa|busta|se hai già lavorato|dopo il ripristino|in fondo alla pagina|nel gruppo|elenco buste|azione|conferma|prova|riquadro|esercitazione|nuovi codici|righe|tab |sezione|badge|domande|stai scrivendo|per ogni|genera buste paga|dipendenti$)/;

  function controlloDi(label) {
    var c = label.control || label.querySelector('input,select,textarea');
    if (!c) { var d = label.nextElementSibling; c = d && d.querySelector ? (d.matches('input,select,textarea') ? d : d.querySelector('input,select,textarea')) : null; }
    return visibile(c) ? c : null;
  }
  function trovaCampo(chiave) {
    var k = norm(chiave).replace(/ \/ .*$/, ''), ll = document.querySelectorAll('label'), migliore = null;
    for (var i = 0; i < ll.length; i++) {
      if (box.contains(ll[i])) continue;
      var t = norm(ll[i].childNodes[0] && ll[i].childNodes[0].nodeType === 3 ? ll[i].childNodes[0].textContent : ll[i].textContent);
      if (!t) continue;
      if (t === k || t.indexOf(k) === 0 || k.indexOf(t) === 0) { var c = controlloDi(ll[i]); if (c) { if (t === k) return c; migliore = migliore || c; } }
    }
    return migliore;
  }
  function trovaPulsante(testo) {
    var t = norm(testo).replace(/^(il |la )?pulsante /, ''), bb = document.querySelectorAll('button, a.btn, input[type=submit]');
    for (var i = 0; i < bb.length; i++) {
      if (!visibile(bb[i])) continue;
      var x = norm(bb[i].value || bb[i].textContent);
      if (x && (x === t || x.indexOf(t) === 0 || t.indexOf(x) === 0)) return bb[i];
    }
    return null;
  }
  function data(v) { var m = /(\d{2})\/(\d{2})\/(\d{4})/.exec(v); return m ? m[3] + '-' + m[2] + '-' + m[1] : null; }
  function fatto(el, v) {
    if (toccati.has(el)) return true;
    var d = data(v);
    if (el.type === 'checkbox') return /lascia|sì|si$|spunta/.test(norm(v)) ? el.checked : toccati.has(el);
    if (el.tagName === 'SELECT') {
      var o = el.options[el.selectedIndex], t = norm(o ? o.text : '');
      return !!t && (t.indexOf(norm(v)) >= 0 || norm(v).indexOf(t) >= 0);
    }
    if (d) return el.value === d;
    var a = norm(el.value), b = norm(v);
    if (!a) return false;
    return a === b || /^\d/.test(b) && parseFloat(a.replace(',', '.')) === parseFloat(b.replace(/\./g, '').replace(',', '.'));
  }

  function puntiDelPasso(sez) {
    var campi = []; try { campi = JSON.parse(sez.dataset.campi || '[]'); } catch (e) {}
    var punti = [], pulsanti = [];
    campi.forEach(function (c) {
      var k = c[0], v = c[1];
      if (/^pulsante/i.test(k)) { var b = trovaPulsante(v.replace(/[«»]/g, '')); if (b) pulsanti.push({el: b, testo: 'Premi <b>«' + esc(v.replace(/[«»]/g, '')) + '»</b>'}); return; }
      if (NON_CAMPI.test(norm(k))) return;
      var el = trovaCampo(k); if (!el) return;
      var verbo = el.tagName === 'SELECT' ? 'scegli' : el.type === 'checkbox' ? '' : 'scrivi';
      punti.push({el: el, v: v, testo: 'In «' + esc(k) + '» ' + verbo + ' <b>' + esc(v) + '</b>'});
    });
    return {punti: punti, pulsanti: pulsanti};
  }

  function spegni() { if (acceso) acceso.classList.remove('gl-brilla'); acceso = null; bolla.hidden = true; }
  function aggiorna() {
    if (spento || box.hidden) return spegni();
    var pos = window.__guidaPos ? window.__guidaPos() : 0, sez = box.querySelector('.guida-passo[data-i="' + pos + '"]');
    if (!sez) return spegni();
    if (pos !== ultimoPasso) { ultimoPasso = pos; toccati = new WeakSet(); }
    var stato = sez.querySelector('.guida-stato .text-success'), finito = stato && /Fatto/.test(stato.textContent);
    var bers = null, ora = '';
    if (finito) {
      bers = box.querySelector('.guida-succ'); ora = '✓ Questo passo è fatto: premi <b>›</b> per il passo successivo.';
    } else if (sez.dataset.qui !== '1') {
      bers = sez.querySelector('.guida-dove a'); ora = '📍 Questo passo si fa in un’altra pagina: premi <b>«Apri la pagina»</b>.';
    } else {
      var pp = puntiDelPasso(sez), primo = null;
      for (var i = 0; i < pp.punti.length; i++) if (!fatto(pp.punti[i].el, pp.punti[i].v)) { primo = pp.punti[i]; break; }
      if (primo) { bers = primo.el; ora = '✍️ ' + primo.testo; }
      else if (pp.pulsanti.length) { bers = pp.pulsanti[0].el; ora = '👉 ' + pp.pulsanti[0].testo; }
      else {
        var letto = sez.querySelector('button[value=fatto]');
        bers = letto || sez.querySelector('.guida-campi');
        ora = letto ? '👀 Segui le indicazioni nella finestra a destra, poi premi <b>«Fatto: ho letto»</b>.' : '👀 Segui le indicazioni di questa tabella, una riga alla volta: il passo si spunta da solo quando è fatto.';
      }
    }
    if (!bers || !(bers.offsetParent !== null)) return spegni();
    if (acceso !== bers) { if (acceso) acceso.classList.remove('gl-brilla'); acceso = bers; bers.classList.add('gl-brilla');
      var r0 = bers.getBoundingClientRect(); if (r0.top < 60 || r0.bottom > innerHeight - 40) bers.scrollIntoView({block: 'center', behavior: 'smooth'}); }
    var n = +pos + 1, tot = box.querySelectorAll('.guida-passo').length;
    var html = '<div class="gl-stiamo"><span>📌 COSA STIAMO FACENDO · PASSO ' + n + ' DI ' + tot + '</span><b>' + esc(sez.dataset.titolo) + '</b>' +
      (sez.dataset.perche ? '<em>' + esc(sez.dataset.perche) + '</em>' : '') + '</div><div class="gl-ora"><b>🎯 ORA TOCCA A TE</b><p>' + ora + '</p></div>';
    if (bolla.dataset.firma !== html) { bolla.innerHTML = html; bolla.dataset.firma = html; }
    bolla.hidden = false;
    posiziona(bers);
  }
  function posiziona(el) {
    var r = el.getBoundingClientRect(), b = bolla.getBoundingClientRect(), m = 12, y, sopra;
    if (r.bottom + m + b.height < innerHeight) { y = r.bottom + m; sopra = false; }
    else if (r.top - m - b.height > 0) { y = r.top - m - b.height; sopra = true; }
    else { y = Math.max(8, innerHeight - b.height - 8); sopra = false; }
    var x = Math.min(Math.max(8, r.left + r.width / 2 - b.width / 2), innerWidth - b.width - 8);
    bolla.style.left = (x + scrollX) + 'px'; bolla.style.top = (y + scrollY) + 'px';
    bolla.style.setProperty('--freccia', Math.min(Math.max(16, r.left + r.width / 2 - x), b.width - 16) + 'px');
    bolla.classList.toggle('sopra', sopra); bolla.classList.toggle('sotto', !sopra);
  }

  // interruttore nella finestra
  var piede = box.querySelector('.guida-piede');
  if (piede) {
    var sw = document.createElement('button'); sw.type = 'button'; sw.className = 'btn btn-sm btn-link gl-spegni';
    var etichetta = function () { sw.textContent = spento ? '💡 Accendi il suggeritore' : '🙈 Spegni il suggeritore'; };
    etichetta(); piede.parentNode.insertBefore(sw, piede.nextSibling);
    sw.addEventListener('click', function () { spento = !spento; scrivi(LS, spento ? '0' : '1'); etichetta(); aggiorna(); });
  }
  document.addEventListener('change', function (e) { if (e.target && !box.contains(e.target)) toccati.add(e.target); aggiorna(); }, true);
  document.addEventListener('input', aggiorna, true);
  document.addEventListener('click', function () { setTimeout(aggiorna, 50); }, true);
  document.addEventListener('mousemove', function (e) {
    if (bolla.hidden) return;
    var b = bolla.getBoundingClientRect();
    bolla.classList.toggle('velata', e.clientX > b.left - 6 && e.clientX < b.right + 6 && e.clientY > b.top - 6 && e.clientY < b.bottom + 6);
  });
  addEventListener('resize', aggiorna);
  addEventListener('scroll', function () { if (acceso && !bolla.hidden) posiziona(acceso); }, {passive: true});
  setInterval(aggiorna, 1000);
  aggiorna();
})();
