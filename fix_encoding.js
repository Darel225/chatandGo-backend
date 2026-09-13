const fs = require('fs');
const path = require('path');

const replacements = {
  'é': 'é', 'è': 'è', 'à': 'à', 'â': 'â', 'ê': 'ê', 
  'ç': 'ç', 'î': 'î', 'ô': 'ô', 'û': 'û', 'ù': 'ù', 'ï': 'ï',
  'désolé': 'désolé', 'Désolé': 'Désolé', 'qualifiés': 'qualifiés', 'déplacer': 'déplacer',
  'Vérification': 'Vérification', 'envoyé': 'envoyé', 'sécurisées': 'sécurisées',
  'é': 'é'
};

function walk(dir) {
  const files = fs.readdirSync(dir);
  for (const file of files) {
    const fullPath = path.join(dir, file);
    if (fs.statSync(fullPath).isDirectory()) {
      if (file !== 'node_modules' && file !== 'venv' && file !== '__pycache__' && !file.startsWith('.')) {
        walk(fullPath);
      }
    } else if (fullPath.endsWith('.py') || fullPath.endsWith('.js') || fullPath.endsWith('.jsx')) {
      let content = fs.readFileSync(fullPath, 'utf8');
      let modified = content;

      for (const [bad, good] of Object.entries(replacements)) {
        modified = modified.split(bad).join(good);
      }

      if (modified !== content) {
        fs.writeFileSync(fullPath, modified, 'utf8');
        console.log('Fixed:', fullPath);
      }
    }
  }
}

walk('.');
