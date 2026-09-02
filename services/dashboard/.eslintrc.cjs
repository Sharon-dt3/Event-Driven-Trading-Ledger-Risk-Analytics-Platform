module.exports = {
  root: true,
  env: { browser: true, es2021: true, node: true },
  ignorePatterns: ['dist', 'build', 'node_modules'],
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    ecmaFeatures: { jsx: true },
  },
  extends: ['eslint:recommended', 'plugin:react/recommended'],
  settings: { react: { version: 'detect' } },
  rules: {
    'react/react-in-jsx-scope': 'off',
    'react/prop-types': 'off',
  },
};
