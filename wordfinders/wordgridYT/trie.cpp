#include "trie.h"
#include <cassert>

Trie::Trie() {
  std::fill(nodes, nodes + NUM_LETTERS, nullptr);
}

Trie::~Trie() {
  Iter i = iter();
  while (i.next()) { delete i.get(); }
}

void Trie::add(const std::string& str) {
  Trie* ptr = this;
  for (char c : str) {
    const int ix = c - 'A';
    assert(ix >= 0 && ix < NUM_LETTERS);
    if (ptr->nodes[ix] == nullptr) {
      ptr->nodes[ix] = new Trie();
    }
    ptr = ptr->nodes[ix];
  }
}

bool Trie::has(const std::string& str) const {
  const Trie* ptr = this;
  for (char c : str) {
    const int ix = c - 'A';
    assert(ix >= 0 && ix < NUM_LETTERS);
    if (ptr->nodes[ix] == nullptr) {
      return false;
    } else {
      ptr = ptr->nodes[ix];
    }
  }
}
