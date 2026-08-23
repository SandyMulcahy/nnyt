#pragma once
#include <string>
#define NUM_LETTERS 26

class Trie {
public:
  class Iter {
  public:
    Iter(Trie** nodes) : n(nodes), ix(-1) {}
    inline int getIx() const { return ix; }
    inline char getLetter() const { return (char)(ix + 'A'); }
    inline Trie* get() const { return n[ix]; }
    bool next() {
      while (true) {
        ix += 1;
        if (ix >= NUM_LETTERS) { return false; }
        if (n[ix] != nullptr) { return true; }
      }
    }

  private:
    int ix;
    Trie** n;
  };

  Trie();
  ~Trie();

  void add(const std::string& str);
  bool has(const std::string& str) const;
  inline bool hasIx(int ix) const { return nodes[ix] != nullptr; }
  inline bool hasLetter(char c) const { return nodes[int(c - 'A')] != nullptr; }
  inline Trie* decend(int ix) const { return nodes[ix]; }

  Iter iter() { return Iter(nodes); }

  Trie* nodes[NUM_LETTERS];
};
